"""Socket.IO server manager and event handling for Supernote server."""

import logging
from http import HTTPStatus
from urllib.parse import parse_qs

import socketio
from aiohttp import web

from supernote.models.socket import (
    SocketHandshakeParams,
    SocketIoClientMessage,
    SocketIoEvent,
    SocketMessageData,
)
from supernote.server.config import ServerConfig
from supernote.server.socket_auth import (
    verify_handshake_signature,
    verify_handshake_token,
)

logger = logging.getLogger(__name__)


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


class SocketIOServerManager:
    """Manages the Socket.IO server lifecycle, authentication, session rooms, and message delivery."""

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self._sio = socketio.AsyncServer(
            async_mode="aiohttp",
            cors_allowed_origins="*",
            allow_eio3=True,
            logger=False,
            engineio_logger=False,
        )
        self._sid_to_user: dict[str, str] = {}
        self._setup_handlers()

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

    def _setup_handlers(self) -> None:
        @self._sio.event
        async def connect(sid: str, environ: dict) -> bool:
            params = _extract_handshake_params(environ)
            secret_key = self.config.auth.secret_key

            # Verify handshake signature
            if not verify_handshake_signature(params, secret_key):
                logger.error(
                    "Socket.IO connect rejected: invalid signature (sid=%s)", sid
                )
                await self._send_error(
                    sid, HTTPStatus.FORBIDDEN, "sign verification failed"
                )
                return False

            # Verify JWT authentication token
            user_id = verify_handshake_token(params.token, secret_key)
            if not user_id:
                logger.error("Socket.IO connect rejected: invalid token (sid=%s)", sid)
                await self._send_error(
                    sid, HTTPStatus.FORBIDDEN, "token verification failed"
                )
                return False

            # Associate session ID with user_id and join user room
            self._sid_to_user[sid] = user_id
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
            logger.info("Socket.IO disconnected for user=%s (sid=%s)", user_id, sid)

        @self._sio.on(SocketIoEvent.CLIENT_MESSAGE.value)
        async def on_client_message(sid: str, data: str) -> None:
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

        @self._sio.on(SocketIoEvent.RATTA_PING.value)
        async def on_ratta_ping(sid: str, data: str) -> None:
            user_id = self._sid_to_user.get(sid)
            logger.debug(
                "Received ratta_ping from user=%s (sid=%s): %s", user_id, sid, data
            )
            await self._sio.emit(
                SocketIoEvent.RATTA_PING.value,
                SocketIoClientMessage.RECEIVED.value,
                to=sid,
            )

    async def send_message(self, user_id: str, message: SocketMessageData) -> None:
        """Send a SocketMessageData event to all connected sessions for a given user.

        Args:
            user_id: Target user email or identifier.
            message: SocketMessageData payload to deliver.
        """
        user_room = f"user_{user_id}"
        payload_str = message.to_json()
        logger.debug("Emitting ServerMessage to room=%s: %s", user_room, payload_str)
        await self._sio.emit(
            SocketIoEvent.SERVER_MESSAGE.value,
            payload_str,
            room=user_room,
        )


def setup_socketio(app: web.Application, config: ServerConfig) -> SocketIOServerManager:
    """Initialize and attach Socket.IO server manager to an aiohttp Application.

    Args:
        app: The aiohttp web Application.
        config: The server configuration instance.

    Returns:
        The configured SocketIOServerManager instance.
    """
    manager = SocketIOServerManager(config)
    manager.attach_to_app(app)
    return manager
