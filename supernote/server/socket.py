"""Socket.IO real-time server manager (`setup_socketio`) and device push broadcaster.

Attaches an `AsyncServer` (`/socket.io/`) to the `aiohttp` application in
`supernote.server.app.create_app`, authenticates client handshakes via
`supernote.server.socket_auth.verify_handshake_signature` and
`supernote.server.services.user.UserService`, responds to device heartbeat pings
(`ratta_ping`), and subscribes to `supernote.server.events.LocalEventBus` to broadcast
file, summary (`digestMessage`), and task (`scheduleTaskMessage`) change notifications
to connected hardware tablets and Web UI sessions.
"""

import logging
import time
from http import HTTPStatus
from urllib.parse import parse_qs

import engineio.packet
import socketio
from aiohttp import web

from supernote.models.base import BooleanEnum
from supernote.models.socket import (
    BaseSocketMessageData,
    DigestMessageTemplate,
    ScheduleMessageTemplate,
    SocketDigestMessageData,
    SocketHandshakeParams,
    SocketIoAction,
    SocketIoClientMessage,
    SocketIoCode,
    SocketIoDigestDataType,
    SocketIoEvent,
    SocketIoFileType,
    SocketIoMessageTemplate,
    SocketIoMessageType,
    SocketMessageData,
    SocketTaskMessageData,
)
from supernote.server.config import ServerConfig
from supernote.server.events import (
    LocalEventBus,
    ScheduleUpdatedEvent,
    SummaryDeletedEvent,
    SummaryTagDeletedEvent,
    SummaryTagUpsertedEvent,
    SummaryUpsertedEvent,
    SyncCompletedEvent,
    VfsItemCopiedEvent,
    VfsItemCreatedEvent,
    VfsItemDeletedEvent,
    VfsItemMovedEvent,
)
from supernote.server.services.user import UserService
from supernote.server.socket_auth import verify_handshake_signature

logger = logging.getLogger(__name__)

_MSG_TYPE_TO_EVENT: dict[str, SocketIoEvent] = {
    SocketIoMessageType.FILE_SYN.value: SocketIoEvent.SERVER_MESSAGE,
    SocketIoMessageType.TASK_SYN.value: SocketIoEvent.TODO,
    SocketIoMessageType.DIGEST_SYN.value: SocketIoEvent.DIGEST,
}


def _parent_dir_path(full_path: str) -> str:
    """Format the parent directory path with a trailing slash (or empty string at root)."""
    cleaned = full_path.strip("/")
    if "/" not in cleaned:
        return ""
    parent, _ = cleaned.rsplit("/", 1)
    return f"{parent}/"


def _extract_handshake_params(environ: dict) -> SocketHandshakeParams:
    """Extract handshake authentication parameters from the WSGI/ASGI connection environment.

    Socket.IO passes the request environment dictionary to the connection handler,
    containing the raw QUERY_STRING sent during transport establishment.
    """
    query_string = environ.get("QUERY_STRING", "")
    parsed_query = parse_qs(query_string)

    token = parsed_query.get("token", [""])[0]
    conn_type = parsed_query.get("type", ["file"])[0]
    random_val = parsed_query.get("random", [""])[0]
    sign = parsed_query.get("sign", [""])[0]

    return SocketHandshakeParams(
        token=token,
        type=conn_type,
        random=random_val,
        sign=sign,
    )


class _CompatAsyncServer(socketio.AsyncServer):
    """Socket.IO AsyncServer with Engine.IO v3 / Socket.IO v2 compatibility."""

    async def _handle_connect(
        self, eio_sid: str, namespace: str, data: object = None
    ) -> None:
        ns = namespace or "/"
        if self.manager.sid_from_eio_sid(eio_sid, ns) is not None:
            return
        await super()._handle_connect(eio_sid, namespace, data)

    async def _handle_eio_connect(self, eio_sid: str, environ: dict) -> None:
        await super()._handle_eio_connect(eio_sid, environ)

        eio_sock = self.eio.sockets[eio_sid]
        original_receive = eio_sock.receive

        async def _receive_with_eio3_ping(
            pkt: engineio.packet.Packet,
        ) -> None:
            if pkt.packet_type == engineio.packet.PING:
                eio_sock.schedule_ping()
                await eio_sock.send(
                    engineio.packet.Packet(engineio.packet.PONG, pkt.data)
                )
                return
            await original_receive(pkt)

        setattr(eio_sock, "receive", _receive_with_eio3_ping)

        await self._handle_connect(eio_sid, "/", None)


class SocketIOServerManager:
    """Manages the Socket.IO server lifecycle, authentication, session rooms, and message delivery."""

    def __init__(
        self,
        config: ServerConfig,
        user_service: UserService,
        event_bus: LocalEventBus | None = None,
    ) -> None:
        self.config = config
        self.user_service = user_service
        self.event_bus = event_bus
        self._sio = _CompatAsyncServer(
            async_mode="aiohttp",
            cors_allowed_origins="*",
            allow_eio3=True,
            logger=False,
            engineio_logger=False,
        )
        self._sid_to_user: dict[str, int] = {}
        self._sid_to_token: dict[str, str] = {}
        self._setup_handlers()
        self._setup_event_bus_subscriptions()

    @property
    def sio(self) -> socketio.AsyncServer:
        """Access the underlying AsyncServer instance."""
        return self._sio

    def attach_to_app(self, app: web.Application) -> None:
        """Attach the Socket.IO server instance to an aiohttp web Application."""
        self._sio.attach(app)
        app["socketio_manager"] = self

    async def _send_error(self, sid: str, status: HTTPStatus, message: str) -> None:
        """Send a SocketMessageData error response to a specific session ID."""
        err_data = SocketMessageData(
            code=str(status.value),
            msg=message,
        )
        await self._sio.emit(
            SocketIoEvent.SERVER_MESSAGE.value,
            err_data.to_json(),
            to=sid,
        )

    async def _verify_active_session(self, sid: str) -> bool:
        """Verify that a connected Socket.IO session still holds an active token."""
        token = self._sid_to_token.get(sid)
        if token and await self.user_service.verify_token(token):
            return True

        user_id = self._sid_to_user.pop(sid, None)
        self._sid_to_token.pop(sid, None)
        logger.warning(
            "Socket.IO session no longer valid for user=%s (sid=%s); disconnecting",
            user_id,
            sid,
        )
        if user_id is not None:
            await self._sio.leave_room(sid, f"user_{user_id}")
        await self._send_error(sid, HTTPStatus.FORBIDDEN, "token verification failed")
        await self._sio.disconnect(sid)
        return False

    def _setup_handlers(self) -> None:
        @self._sio.event
        async def connect(sid: str, environ: dict) -> bool:
            params = _extract_handshake_params(environ)

            # Verify handshake signature
            if not verify_handshake_signature(params):
                logger.error(
                    "Socket.IO connect rejected: invalid signature (sid=%s)", sid
                )
                await self._send_error(
                    sid, HTTPStatus.FORBIDDEN, "sign verification failed"
                )
                return False

            # Verify stateful session token
            session = await self.user_service.verify_token(params.token)
            if not session:
                logger.error("Socket.IO connect rejected: invalid token (sid=%s)", sid)
                await self._send_error(
                    sid, HTTPStatus.FORBIDDEN, "token verification failed"
                )
                return False

            # Associate session ID with user room
            user_id = session.user_id
            self._sid_to_user[sid] = user_id
            self._sid_to_token[sid] = params.token
            user_room = f"user_{user_id}"
            await self._sio.enter_room(sid, user_room)
            logger.info(
                "Socket.IO connection established for user=%s (sid=%s, room=%s)",
                user_id,
                sid,
                user_room,
            )
            return True

        @self._sio.event
        async def disconnect(sid: str) -> None:
            user_id = self._sid_to_user.pop(sid, None)
            self._sid_to_token.pop(sid, None)
            logger.info("Socket.IO disconnected for user=%s (sid=%s)", user_id, sid)

        @self._sio.on(SocketIoEvent.CLIENT_MESSAGE.value)
        async def on_client_message(
            sid: str, data: object = None, *_args: object
        ) -> None:
            if not await self._verify_active_session(sid):
                return

            user_id = self._sid_to_user.get(sid)
            logger.debug(
                "Received ClientMessage from user=%s (sid=%s): %s", user_id, sid, data
            )

            if data == SocketIoClientMessage.STATUS.value:
                # Heartbeat check reply
                await self._sio.emit(
                    SocketIoEvent.SERVER_MESSAGE.value,
                    "true",
                    to=sid,
                )
            elif data == SocketIoClientMessage.RECEIVED.value:
                # Client delivery acknowledgment
                logger.debug("Client ACK received for user=%s (sid=%s)", user_id, sid)

        @self._sio.on(SocketIoEvent.TODO.value)
        async def on_todo_ack(sid: str, data: object = None, *_args: object) -> None:
            if not await self._verify_active_session(sid):
                return

            user_id = self._sid_to_user.get(sid)
            if data == SocketIoClientMessage.RECEIVED.value:
                logger.debug(
                    "Client to-do ACK received for user=%s (sid=%s)", user_id, sid
                )

        @self._sio.on(SocketIoEvent.DIGEST.value)
        async def on_digest_ack(sid: str, data: object = None, *_args: object) -> None:
            if not await self._verify_active_session(sid):
                return

            user_id = self._sid_to_user.get(sid)
            if data == SocketIoClientMessage.RECEIVED.value:
                logger.debug(
                    "Client digest ACK received for user=%s (sid=%s)", user_id, sid
                )

        @self._sio.on(SocketIoEvent.RATTA_PING.value)
        async def on_ratta_ping(sid: str, data: object = None, *_args: object) -> None:
            if not await self._verify_active_session(sid):
                return

            user_id = self._sid_to_user.get(sid)
            logger.debug(
                "Received ratta_ping from user=%s (sid=%s): %s", user_id, sid, data
            )
            await self._sio.emit(
                SocketIoEvent.RATTA_PING.value,
                SocketIoClientMessage.RECEIVED.value,
                to=sid,
            )

    def _setup_event_bus_subscriptions(self) -> None:
        """Subscribe to internal LocalEventBus domain events and translate them into Socket.IO pushes."""
        if self.event_bus is None:
            return
        self.event_bus.subscribe(SyncCompletedEvent, self._handle_sync_completed)
        self.event_bus.subscribe(ScheduleUpdatedEvent, self._handle_schedule_updated)
        self.event_bus.subscribe(
            SummaryTagUpsertedEvent, self._handle_summary_tag_upserted
        )
        self.event_bus.subscribe(
            SummaryTagDeletedEvent, self._handle_summary_tag_deleted
        )
        self.event_bus.subscribe(SummaryUpsertedEvent, self._handle_summary_upserted)
        self.event_bus.subscribe(SummaryDeletedEvent, self._handle_summary_deleted)
        self.event_bus.subscribe(VfsItemCreatedEvent, self._handle_vfs_item_created)
        self.event_bus.subscribe(VfsItemMovedEvent, self._handle_vfs_item_moved)
        self.event_bus.subscribe(VfsItemCopiedEvent, self._handle_vfs_item_copied)
        self.event_bus.subscribe(VfsItemDeletedEvent, self._handle_vfs_item_deleted)

    async def _handle_sync_completed(self, event: SyncCompletedEvent) -> None:
        """Emit a STARTSYNC FILE-SYN notification when a device completes a sync session."""
        now_ms = int(time.time() * 1000)
        await self.send_message(
            event.user_id,
            SocketMessageData(
                code=str(SocketIoCode.SUCCESS.value),
                msg="Success",
                timestamp=now_ms,
                msg_type=SocketIoMessageType.FILE_SYN,
                data=[
                    SocketIoMessageTemplate(
                        message_type=SocketIoAction.STARTSYNC,
                        equipment_no=event.equipment_no,
                        timestamp=now_ms,
                    )
                ],
            ),
        )

    async def _handle_schedule_updated(self, event: ScheduleUpdatedEvent) -> None:
        """Emit a QUERY TASK-SYN notification when a schedule task group or task is mutated."""
        now_ms = int(time.time() * 1000)
        await self.send_message(
            event.user_id,
            SocketTaskMessageData(
                code=str(SocketIoCode.SUCCESS.value),
                msg="Success",
                timestamp=now_ms,
                msg_type=SocketIoMessageType.TASK_SYN,
                data=[
                    ScheduleMessageTemplate(
                        message_type=SocketIoAction.QUERY,
                        equipment_no=event.equipment_no,
                        task_list_id=event.task_list_id,
                        task_id=event.task_id,
                        timestamp=now_ms,
                    )
                ],
            ),
        )

    async def _handle_summary_tag_upserted(
        self, event: SummaryTagUpsertedEvent
    ) -> None:
        """Emit an ADD_DIGEST or UPDATE_DIGEST DIGEST-SYN notification when a summary tag is upserted."""
        now_ms = int(time.time() * 1000)
        action = (
            SocketIoAction.ADD_DIGEST if event.is_new else SocketIoAction.UPDATE_DIGEST
        )
        tag = event.tag
        await self.send_message(
            event.user_id,
            SocketDigestMessageData(
                code=str(SocketIoCode.SUCCESS.value),
                msg="Success",
                timestamp=now_ms,
                msg_type=SocketIoMessageType.DIGEST_SYN,
                data=[
                    DigestMessageTemplate(
                        message_type=action,
                        data_type=SocketIoDigestDataType.SUMMARY_TAG,
                        equipment_no=event.equipment_no,
                        id=tag.id,
                        name=tag.name,
                        unique_identifier=tag.unique_identifier,
                        create_time=(
                            str(tag.created_at) if tag.created_at is not None else None
                        ),
                        timestamp=now_ms,
                    )
                ],
            ),
        )

    async def _handle_summary_tag_deleted(self, event: SummaryTagDeletedEvent) -> None:
        """Emit a DELETE_DIGEST DIGEST-SYN notification when a summary tag is deleted."""
        now_ms = int(time.time() * 1000)
        await self.send_message(
            event.user_id,
            SocketDigestMessageData(
                code=str(SocketIoCode.SUCCESS.value),
                msg="Success",
                timestamp=now_ms,
                msg_type=SocketIoMessageType.DIGEST_SYN,
                data=[
                    DigestMessageTemplate(
                        message_type=SocketIoAction.DELETE_DIGEST,
                        data_type=SocketIoDigestDataType.SUMMARY_TAG,
                        equipment_no=event.equipment_no,
                        id=event.tag_id,
                        timestamp=now_ms,
                    )
                ],
            ),
        )

    async def _handle_summary_upserted(self, event: SummaryUpsertedEvent) -> None:
        """Emit an ADD_DIGEST or UPDATE_DIGEST DIGEST-SYN notification when a summary group or item is upserted."""
        now_ms = int(time.time() * 1000)
        action = (
            SocketIoAction.ADD_DIGEST if event.is_new else SocketIoAction.UPDATE_DIGEST
        )
        summary = event.summary
        is_group = summary.is_summary_group == BooleanEnum.YES
        data_type = (
            SocketIoDigestDataType.SUMMARY_GROUP
            if is_group
            else SocketIoDigestDataType.SUMMARY
        )
        await self.send_message(
            event.user_id,
            SocketDigestMessageData(
                code=str(SocketIoCode.SUCCESS.value),
                msg="Success",
                timestamp=now_ms,
                msg_type=SocketIoMessageType.DIGEST_SYN,
                data=[
                    DigestMessageTemplate(
                        message_type=action,
                        data_type=data_type,
                        equipment_no=event.equipment_no,
                        id=summary.id,
                        file_id=summary.file_id,
                        name=summary.name,
                        user_id=summary.user_id,
                        unique_identifier=summary.unique_identifier,
                        parent_unique_identifier=summary.parent_unique_identifier,
                        content=summary.content,
                        source_path=summary.source_path,
                        data_source=summary.data_source,
                        source_type=summary.source_type,
                        is_summary_group=(
                            summary.is_summary_group.value
                            if summary.is_summary_group is not None
                            else None
                        ),
                        description=summary.description,
                        tags=summary.tags,
                        md5_hash=summary.md5_hash,
                        metadata=summary.metadata,
                        comment_str=summary.comment_str,
                        comment_handwrite_name=summary.comment_handwrite_name,
                        handwrite_inner_name=summary.handwrite_inner_name,
                        handwrite_md5=summary.handwrite_md5,
                        creation_time=summary.creation_time,
                        last_modified_time=summary.last_modified_time,
                        is_deleted=(
                            summary.is_deleted.value
                            if summary.is_deleted is not None
                            else None
                        ),
                        create_time=(
                            str(summary.create_time)
                            if summary.create_time is not None
                            else None
                        ),
                        update_time=(
                            str(summary.update_time)
                            if summary.update_time is not None
                            else None
                        ),
                        timestamp=now_ms,
                        author=summary.author,
                    )
                ],
            ),
        )

    async def _handle_summary_deleted(self, event: SummaryDeletedEvent) -> None:
        """Emit a DELETE_DIGEST DIGEST-SYN notification when a summary group or item is deleted."""
        now_ms = int(time.time() * 1000)
        data_type = (
            SocketIoDigestDataType.SUMMARY_GROUP
            if event.is_summary_group
            else SocketIoDigestDataType.SUMMARY
        )
        await self.send_message(
            event.user_id,
            SocketDigestMessageData(
                code=str(SocketIoCode.SUCCESS.value),
                msg="Success",
                timestamp=now_ms,
                msg_type=SocketIoMessageType.DIGEST_SYN,
                data=[
                    DigestMessageTemplate(
                        message_type=SocketIoAction.DELETE_DIGEST,
                        data_type=data_type,
                        equipment_no=event.equipment_no,
                        id=event.summary_id,
                        timestamp=now_ms,
                    )
                ],
            ),
        )

    async def _handle_vfs_item_created(self, event: VfsItemCreatedEvent) -> None:
        """Emit an ADDFOLDER or DOWNLOADFILE FILE-SYN notification when a VFS item is created or restored."""
        now_ms = int(time.time() * 1000)
        parent_path = _parent_dir_path(event.full_path)
        file_type = (
            SocketIoFileType.FOLDER if event.is_folder else SocketIoFileType.FILE
        )
        action = SocketIoAction.ADDFOLDER if event.is_folder else SocketIoAction.ADDFILE
        await self.send_message(
            event.user_id,
            SocketMessageData(
                code=str(SocketIoCode.SUCCESS.value),
                msg="Success",
                timestamp=now_ms,
                msg_type=SocketIoMessageType.FILE_SYN,
                data=[
                    SocketIoMessageTemplate(
                        message_type=action,
                        equipment_no=event.equipment_no,
                        file_type=file_type,
                        id=event.item_id,
                        original_name=event.name,
                        new_name=event.name,
                        md5=None if event.is_folder else event.md5,
                        size=0 if event.is_folder else event.size,
                        directory_id=event.parent_id,
                        go_directory_id=None,
                        original_path=parent_path,
                        new_path=parent_path,
                        timestamp=now_ms,
                    )
                ],
            ),
        )

    async def _handle_vfs_item_moved(self, event: VfsItemMovedEvent) -> None:
        """Emit a MODIFYFOLDER/MODIFYFILE or MOVEFOLDER/MOVEFILE FILE-SYN notification."""
        now_ms = int(time.time() * 1000)
        original_path = _parent_dir_path(event.original_full_path)
        new_path = _parent_dir_path(event.new_full_path)
        file_type = (
            SocketIoFileType.FOLDER if event.is_folder else SocketIoFileType.FILE
        )
        is_same_dir = event.original_parent_id == event.new_parent_id
        if is_same_dir:
            action = (
                SocketIoAction.MODIFYFOLDER
                if event.is_folder
                else SocketIoAction.MODIFYFILE
            )
            go_dir_id = None
        else:
            action = (
                SocketIoAction.MOVEFOLDER
                if event.is_folder
                else SocketIoAction.MOVEFILE
            )
            go_dir_id = None if event.is_folder else event.new_parent_id
        await self.send_message(
            event.user_id,
            SocketMessageData(
                code=str(SocketIoCode.SUCCESS.value),
                msg="Success",
                timestamp=now_ms,
                msg_type=SocketIoMessageType.FILE_SYN,
                data=[
                    SocketIoMessageTemplate(
                        message_type=action,
                        equipment_no=event.equipment_no,
                        file_type=file_type,
                        id=event.item_id,
                        original_name=event.original_name,
                        new_name=event.new_name,
                        md5=None if event.is_folder else event.md5,
                        size=0 if event.is_folder else event.size,
                        directory_id=event.new_parent_id,
                        go_directory_id=go_dir_id,
                        original_path=original_path,
                        new_path=new_path,
                        timestamp=now_ms,
                    )
                ],
            ),
        )

    async def _handle_vfs_item_copied(self, event: VfsItemCopiedEvent) -> None:
        """Emit a COPYFOLDER or COPYFILE FILE-SYN notification when a VFS item is copied."""
        now_ms = int(time.time() * 1000)
        original_path = _parent_dir_path(event.original_full_path)
        new_path = _parent_dir_path(event.new_full_path)
        file_type = (
            SocketIoFileType.FOLDER if event.is_folder else SocketIoFileType.FILE
        )
        action = (
            SocketIoAction.COPYFOLDER if event.is_folder else SocketIoAction.COPYFILE
        )
        await self.send_message(
            event.user_id,
            SocketMessageData(
                code=str(SocketIoCode.SUCCESS.value),
                msg="Success",
                timestamp=now_ms,
                msg_type=SocketIoMessageType.FILE_SYN,
                data=[
                    SocketIoMessageTemplate(
                        message_type=action,
                        equipment_no=event.equipment_no,
                        file_type=file_type,
                        id=event.source_id,
                        new_id=event.new_id,
                        original_name=event.original_name,
                        new_name=event.new_name,
                        md5=None if event.is_folder else event.md5,
                        size=0 if event.is_folder else event.size,
                        directory_id=event.source_parent_id,
                        go_directory_id=event.new_parent_id,
                        original_path=original_path,
                        new_path=new_path,
                        timestamp=now_ms,
                    )
                ],
            ),
        )

    async def _handle_vfs_item_deleted(self, event: VfsItemDeletedEvent) -> None:
        """Emit a DELETEFOLDER or DELETEFILE FILE-SYN notification when a VFS item is soft-deleted."""
        now_ms = int(time.time() * 1000)
        original_path = _parent_dir_path(event.full_path)
        file_type = (
            SocketIoFileType.FOLDER if event.is_folder else SocketIoFileType.FILE
        )
        action = (
            SocketIoAction.DELETEFOLDER
            if event.is_folder
            else SocketIoAction.DELETEFILE
        )
        await self.send_message(
            event.user_id,
            SocketMessageData(
                code=str(SocketIoCode.SUCCESS.value),
                msg="Success",
                timestamp=now_ms,
                msg_type=SocketIoMessageType.FILE_SYN,
                data=[
                    SocketIoMessageTemplate(
                        message_type=action,
                        equipment_no=event.equipment_no,
                        file_type=file_type,
                        id=event.item_id,
                        original_name=event.name,
                        new_name=None,
                        md5=None if event.is_folder else event.md5,
                        size=0 if event.is_folder else event.size,
                        directory_id=event.parent_id,
                        go_directory_id=None,
                        original_path=original_path,
                        new_path=None,
                        timestamp=now_ms,
                    )
                ],
            ),
        )

    async def send_message(
        self,
        user_id: int,
        message: BaseSocketMessageData,
    ) -> None:
        """Send a Socket.IO message envelope to all connected sessions for a given user.

        Args:
            user_id: Target numeric user ID.
            message: Socket.IO envelope payload to deliver.
        """
        sids = [sid for sid, uid in list(self._sid_to_user.items()) if uid == user_id]
        for sid in sids:
            await self._verify_active_session(sid)
        user_room = f"user_{user_id}"

        if message.code is None:
            message.code = str(SocketIoCode.SUCCESS.value)

        msg_type_str = (
            message.msg_type.value
            if isinstance(message.msg_type, SocketIoMessageType)
            else str(message.msg_type or "")
        )
        resolved_event = _MSG_TYPE_TO_EVENT.get(
            msg_type_str, SocketIoEvent.SERVER_MESSAGE
        ).value

        payload_str = message.to_json()
        logger.debug(
            "Emitting %s to room=%s: %s", resolved_event, user_room, payload_str
        )
        await self._sio.emit(
            resolved_event,
            payload_str,
            room=user_room,
        )


def setup_socketio(
    app: web.Application,
    config: ServerConfig,
    user_service: UserService,
    event_bus: LocalEventBus | None = None,
) -> SocketIOServerManager:
    """Initialize and attach Socket.IO server manager to an aiohttp Application.

    Args:
        app: The aiohttp web Application.
        config: The server configuration instance.
        user_service: The user authentication and session service.
        event_bus: Optional LocalEventBus instance for domain event subscriptions.

    Returns:
        The configured SocketIOServerManager instance.
    """
    manager = SocketIOServerManager(config, user_service, event_bus)
    manager.attach_to_app(app)
    return manager
