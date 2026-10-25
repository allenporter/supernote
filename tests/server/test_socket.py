"""Integration tests for Socket.IO server handler and client interaction."""

import asyncio
import hashlib
from collections.abc import AsyncGenerator, Callable

import aiohttp
import jwt
import pytest
from aiohttp.test_utils import TestServer
from socketio.exceptions import ConnectionError as SocketIOConnectionError

from supernote.client.exceptions import SupernoteSocketError
from supernote.client.socket import SupernoteSocketClient
from supernote.models.socket import (
    DigestMessageTemplate,
    ScheduleMessageTemplate,
    SocketDigestMessageData,
    SocketHandshakeParams,
    SocketIoAction,
    SocketIoCode,
    SocketIoDigestDataType,
    SocketIoEvent,
    SocketIoFileType,
    SocketIoMessageTemplate,
    SocketIoMessageType,
    SocketMessageData,
    SocketTaskMessageData,
)
from supernote.models.summary import (
    AddSummaryDTO,
    AddSummaryGroupDTO,
    UpdateSummaryDTO,
    UpdateSummaryGroupDTO,
)
from supernote.server.app import create_app
from supernote.server.config import ServerConfig
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.events import (
    LocalEventBus,
    SyncCompletedEvent,
)
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.schedule import ScheduleService
from supernote.server.services.summary import SummaryService
from supernote.server.services.user import JWT_ALGORITHM, UserService
from supernote.server.socket import SocketIOServerManager
from supernote.server.socket_auth import compute_handshake_signature


def _make_handshake_params(
    token: str, conn_type: str = "file", random_val: str = "12345"
) -> SocketHandshakeParams:
    return SocketHandshakeParams(
        token=token,
        type=conn_type,
        random=random_val,
        sign=compute_handshake_signature(token, conn_type, random_val),
    )


@pytest.fixture
async def socketio_server(
    server_config: ServerConfig,
    create_test_user: None,
) -> AsyncGenerator[TestServer]:
    """Create and start a running TestServer hosting the Supernote app with Socket.IO."""
    app = create_app(server_config)
    server = TestServer(app)
    await server.start_server()
    yield server
    await server.close()


@pytest.fixture
def create_socket_client(
    socketio_server: TestServer,
) -> Callable[[], SupernoteSocketClient]:
    """Factory fixture providing SupernoteSocketClient instances pre-wired to the server."""
    host = f"http://{socketio_server.host}:{socketio_server.port}"

    def _factory() -> SupernoteSocketClient:
        return SupernoteSocketClient(host=host)

    return _factory


@pytest.fixture
def socket_client(
    create_socket_client: Callable[[], SupernoteSocketClient],
) -> SupernoteSocketClient:
    """Fixture providing a default pre-configured SupernoteSocketClient instance."""
    return create_socket_client()


@pytest.mark.asyncio
async def test_socketio_ping_pong(
    socketio_server: TestServer,
    socket_client: SupernoteSocketClient,
) -> None:
    user_service: UserService = socketio_server.app["user_service"]
    token_a = await user_service.create_session("test@example.com")
    params_a = _make_handshake_params(token_a)

    await socket_client.connect(params_a)
    assert socket_client.is_connected

    # Send ratta_ping and verify success
    await socket_client.ping(timeout=5.0)

    await socket_client.disconnect()
    assert not socket_client.is_connected


@pytest.mark.asyncio
async def test_socketio_status_heartbeat(
    socketio_server: TestServer,
    socket_client: SupernoteSocketClient,
) -> None:
    user_service: UserService = socketio_server.app["user_service"]
    token_a = await user_service.create_session("test@example.com")
    params_a = _make_handshake_params(token_a)

    await socket_client.connect(params_a)
    assert socket_client.is_connected

    # Check status and verify success
    await socket_client.check_status(timeout=5.0)

    await socket_client.disconnect()


@pytest.fixture
def additional_users() -> list[str]:
    return ["a@example.com"]


@pytest.mark.asyncio
async def test_socketio_multi_user_message_isolation(
    socketio_server: TestServer,
    create_socket_client: Callable[[], SupernoteSocketClient],
    create_test_user: None,
) -> None:
    user_service: UserService = socketio_server.app["user_service"]
    user_a = "test@example.com"
    user_b = "a@example.com"
    user_a_id = await user_service.get_user_id(user_a)

    token_a = await user_service.create_session(user_a)
    token_b = await user_service.create_session(user_b)

    params_a = _make_handshake_params(token_a)
    params_b = _make_handshake_params(token_b)

    client_a = create_socket_client()
    client_b = create_socket_client()

    await client_a.connect(params_a)
    await client_b.connect(params_b)

    assert client_a.is_connected
    assert client_b.is_connected

    manager: SocketIOServerManager = socketio_server.app["socketio_manager"]
    assert manager.sio is not None

    # Send a message targeted ONLY to User A
    msg_data_a = SocketMessageData(
        code="200",
        msg="update notification",
        timestamp=1700000000000,
        msg_type=SocketIoMessageType.FILE_SYN,
        data=[
            SocketIoMessageTemplate(
                message_type=SocketIoAction.ADDFILE,
                equipment_no="SN123",
                file_type=SocketIoFileType.FILE,
                id=101,
                original_name="NoteA.note",
            )
        ],
    )

    await manager.send_message(user_a_id, msg_data_a)

    # User A receives the targeted message
    received_a = await anext(client_a.messages())
    assert isinstance(received_a, SocketMessageData)
    assert received_a.code == "200"
    assert len(received_a.data) == 1
    assert received_a.data[0].original_name == "NoteA.note"

    # User B should not receive any message
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(client_b.messages()), timeout=0.05)

    await client_a.disconnect()
    await client_b.disconnect()


@pytest.mark.asyncio
async def test_socketio_connect_unauthorized(
    socket_client: SupernoteSocketClient,
) -> None:
    invalid_params = SocketHandshakeParams(
        token="some-token",
        type="file",
        random="123",
        sign="invalid_signature",
    )

    with pytest.raises(SocketIOConnectionError):
        await socket_client.connect(invalid_params)

    assert not socket_client.is_connected


@pytest.mark.asyncio
async def test_socketio_connect_invalid_token(
    socket_client: SupernoteSocketClient,
    server_config: ServerConfig,
) -> None:
    # Valid signature but invalid JWT token string
    invalid_token_params = _make_handshake_params("bad.jwt.token")

    with pytest.raises(SocketIOConnectionError):
        await socket_client.connect(invalid_token_params)

    assert not socket_client.is_connected

    # Valid JWT signature, but never persisted in CoordinationService
    secret = server_config.auth.secret_key
    unpersisted_token = jwt.encode(
        {"sub": "test@example.com"}, secret, algorithm=JWT_ALGORITHM
    )
    unpersisted_params = _make_handshake_params(unpersisted_token)

    with pytest.raises(SocketIOConnectionError):
        await socket_client.connect(unpersisted_params)

    assert not socket_client.is_connected


@pytest.mark.asyncio
async def test_socketio_client_received_ack(
    socketio_server: TestServer,
    socket_client: SupernoteSocketClient,
) -> None:
    user_service: UserService = socketio_server.app["user_service"]
    token_a = await user_service.create_session("test@example.com")
    params_a = _make_handshake_params(token_a)

    await socket_client.connect(params_a)
    assert socket_client.is_connected

    # Send client delivery ACK and unhandled message on ClientMessage channel
    await socket_client.send_client_message("Received")
    await socket_client.send_client_message("other")

    await socket_client.ping(timeout=5.0)
    await socket_client.disconnect()


@pytest.mark.asyncio
async def test_socketio_client_messages_async_iterator(
    socketio_server: TestServer,
    socket_client: SupernoteSocketClient,
) -> None:
    user_service: UserService = socketio_server.app["user_service"]
    user_email = "test@example.com"
    user_id = await user_service.get_user_id(user_email)
    token_a = await user_service.create_session(user_email)
    params_a = _make_handshake_params(token_a)

    await socket_client.connect(params_a)

    manager: SocketIOServerManager = socketio_server.app["socketio_manager"]
    msg_data = SocketMessageData(
        msg="test message",
        timestamp=1700000000000,
        msg_type=SocketIoMessageType.FILE_SYN,
    )
    await manager.send_message(user_id, msg_data)

    async for msg in socket_client.messages():
        assert isinstance(msg, SocketMessageData)
        assert msg.code == "200"
        assert msg.msg == "test message"
        break

    # Also test TASK-SYN ('to-do' channel) and DIGEST-SYN ('digest' channel) routing
    task_msg = SocketTaskMessageData(
        msg="task sync",
        timestamp=1700000000001,
        data=[
            ScheduleMessageTemplate(
                message_type=SocketIoAction.QUERY,
                equipment_no="SN123",
                task_list_id="501",
                task_id="1002",
            )
        ],
    )
    await manager.send_message(user_id, task_msg)
    received_task = await anext(socket_client.messages())
    assert isinstance(received_task, SocketTaskMessageData)
    assert received_task.code == "200"
    assert received_task.msg_type == SocketIoMessageType.TASK_SYN
    assert received_task.msg == "task sync"
    assert len(received_task.data) == 1
    assert received_task.data[0].task_list_id == "501"

    digest_msg = SocketDigestMessageData(
        msg="digest sync",
        timestamp=1700000000002,
        data=[
            DigestMessageTemplate(
                message_type=SocketIoAction.ADD_DIGEST,
                data_type=SocketIoDigestDataType.SUMMARY,
                equipment_no="SN123",
                id=302,
            )
        ],
    )
    await manager.send_message(user_id, digest_msg)
    received_digest = await anext(socket_client.messages())
    assert isinstance(received_digest, SocketDigestMessageData)
    assert received_digest.code == "200"
    assert received_digest.msg_type == SocketIoMessageType.DIGEST_SYN
    assert received_digest.msg == "digest sync"
    assert len(received_digest.data) == 1
    assert received_digest.data[0].id == 302

    # Verify LocalEventBus SyncCompletedEvent triggers STARTSYNC on ServerMessage
    event_bus: LocalEventBus = socketio_server.app["event_bus"]
    await event_bus.publish(
        SyncCompletedEvent(
            user_id=user_id,
            equipment_no="SN999",
        )
    )
    received_sync = await anext(socket_client.messages())
    assert isinstance(received_sync, SocketMessageData)
    assert received_sync.msg_type == SocketIoMessageType.FILE_SYN
    assert len(received_sync.data) == 1
    assert received_sync.data[0].message_type == SocketIoAction.STARTSYNC
    assert received_sync.data[0].equipment_no == "SN999"

    await socket_client.disconnect()


@pytest.mark.asyncio
async def test_socketio_revoked_session_disconnected_on_heartbeat_and_send(
    socketio_server: TestServer,
    create_socket_client: Callable[[], SupernoteSocketClient],
) -> None:
    """Verify revoked sessions are disconnected on heartbeat or outbound send_message."""
    user_service: UserService = socketio_server.app["user_service"]
    manager: SocketIOServerManager = socketio_server.app["socketio_manager"]
    user_email = "test@example.com"
    user_id = await user_service.get_user_id(user_email)

    token_ping = await user_service.create_session(user_email)
    token_status = await user_service.create_session(user_email)
    token_send = await user_service.create_session(user_email)

    client_ping = create_socket_client()
    client_status = create_socket_client()
    client_send = create_socket_client()

    await client_ping.connect(_make_handshake_params(token_ping))
    await client_status.connect(_make_handshake_params(token_status))
    await client_send.connect(_make_handshake_params(token_send))

    # Revoke token_ping and verify ratta_ping fails and disconnects
    await user_service.logout(token_ping)
    with pytest.raises(TimeoutError):
        await client_ping.ping(timeout=0.1)

    # Revoke token_status and verify status check fails and disconnects
    await user_service.logout(token_status)
    with pytest.raises(TimeoutError):
        await client_status.check_status(timeout=0.1)

    # Revoke token_send and verify outbound send_message disconnects instead of delivering
    await user_service.logout(token_send)
    msg_data = SocketMessageData(
        code="200",
        msg="secret update",
        timestamp=1700000000000,
        msg_type=SocketIoMessageType.FILE_SYN,
    )
    await manager.send_message(user_id, msg_data)

    received = await anext(client_send.messages())
    assert isinstance(received, SocketMessageData)
    assert received.code == "403"
    assert received.msg == "token verification failed"

    await client_ping.disconnect()
    await client_status.disconnect()
    await client_send.disconnect()


@pytest.mark.asyncio
async def test_socketio_schedule_service_events_publish_task_syn(
    socketio_server: TestServer,
    socket_client: SupernoteSocketClient,
) -> None:
    """Verify ScheduleService mutations publish ScheduleUpdatedEvent and emit TASK-SYN messages."""
    user_service: UserService = socketio_server.app["user_service"]
    schedule_service: ScheduleService = socketio_server.app["schedule_service"]
    user_email = "test@example.com"
    user_id = await user_service.get_user_id(user_email)

    token = await user_service.create_session(user_email)
    await socket_client.connect(_make_handshake_params(token))

    # Create task group -> emits TASK-SYN QUERY with task_list_id
    group = await schedule_service.create_group(user_id, "Work Tasks")
    msg = await anext(socket_client.messages())
    assert isinstance(msg, SocketTaskMessageData)
    assert msg == SocketTaskMessageData(
        code=str(SocketIoCode.SUCCESS.value),
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.TASK_SYN,
        data=[
            ScheduleMessageTemplate(
                message_type=SocketIoAction.QUERY,
                equipment_no=None,
                task_list_id=group.task_list_id,
                task_id=None,
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Update task group -> emits TASK-SYN QUERY with task_list_id
    await schedule_service.update_group(user_id, group.task_list_id, "Work Updated")
    msg = await anext(socket_client.messages())
    assert isinstance(msg, SocketTaskMessageData)
    assert msg == SocketTaskMessageData(
        code=str(SocketIoCode.SUCCESS.value),
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.TASK_SYN,
        data=[
            ScheduleMessageTemplate(
                message_type=SocketIoAction.QUERY,
                equipment_no=None,
                task_list_id=group.task_list_id,
                task_id=None,
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Create task -> emits TASK-SYN QUERY with task_list_id and task_id
    task = await schedule_service.create_task(
        user_id, group_id=group.task_list_id, title="Write tests"
    )
    msg = await anext(socket_client.messages())
    assert isinstance(msg, SocketTaskMessageData)
    assert msg == SocketTaskMessageData(
        code=str(SocketIoCode.SUCCESS.value),
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.TASK_SYN,
        data=[
            ScheduleMessageTemplate(
                message_type=SocketIoAction.QUERY,
                equipment_no=None,
                task_list_id=group.task_list_id,
                task_id=task.task_id,
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Update task -> emits TASK-SYN QUERY with task_list_id and task_id
    await schedule_service.update_task(
        user_id, task.task_id, title="Write thorough tests"
    )
    msg = await anext(socket_client.messages())
    assert isinstance(msg, SocketTaskMessageData)
    assert msg == SocketTaskMessageData(
        code=str(SocketIoCode.SUCCESS.value),
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.TASK_SYN,
        data=[
            ScheduleMessageTemplate(
                message_type=SocketIoAction.QUERY,
                equipment_no=None,
                task_list_id=group.task_list_id,
                task_id=task.task_id,
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Batch update tasks -> emits TASK-SYN QUERY with task_list_id
    await schedule_service.batch_update_tasks(
        user_id, [{"task_id": task.task_id, "sort": 1}]
    )
    msg = await anext(socket_client.messages())
    assert isinstance(msg, SocketTaskMessageData)
    assert msg == SocketTaskMessageData(
        code=str(SocketIoCode.SUCCESS.value),
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.TASK_SYN,
        data=[
            ScheduleMessageTemplate(
                message_type=SocketIoAction.QUERY,
                equipment_no=None,
                task_list_id=group.task_list_id,
                task_id=None,
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Delete task -> emits TASK-SYN QUERY with task_list_id and task_id
    await schedule_service.delete_task(user_id, task.task_id)
    msg = await anext(socket_client.messages())
    assert isinstance(msg, SocketTaskMessageData)
    assert msg == SocketTaskMessageData(
        code=str(SocketIoCode.SUCCESS.value),
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.TASK_SYN,
        data=[
            ScheduleMessageTemplate(
                message_type=SocketIoAction.QUERY,
                equipment_no=None,
                task_list_id=group.task_list_id,
                task_id=task.task_id,
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Add a second task and clear group tasks -> emits TASK-SYN QUERY with task_list_id
    task2 = await schedule_service.create_task(
        user_id, group_id=group.task_list_id, title="Task to clear"
    )
    msg_task2 = await anext(socket_client.messages())
    assert isinstance(msg_task2, SocketTaskMessageData)
    assert msg_task2.data[0].task_id == task2.task_id

    await schedule_service.clear_group_tasks(user_id, group.task_list_id)
    msg = await anext(socket_client.messages())
    assert isinstance(msg, SocketTaskMessageData)
    assert msg == SocketTaskMessageData(
        code=str(SocketIoCode.SUCCESS.value),
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.TASK_SYN,
        data=[
            ScheduleMessageTemplate(
                message_type=SocketIoAction.QUERY,
                equipment_no=None,
                task_list_id=group.task_list_id,
                task_id=None,
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Delete group -> emits TASK-SYN QUERY with task_list_id
    await schedule_service.delete_group(user_id, group.task_list_id)
    msg = await anext(socket_client.messages())
    assert isinstance(msg, SocketTaskMessageData)
    assert msg == SocketTaskMessageData(
        code=str(SocketIoCode.SUCCESS.value),
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.TASK_SYN,
        data=[
            ScheduleMessageTemplate(
                message_type=SocketIoAction.QUERY,
                equipment_no=None,
                task_list_id=group.task_list_id,
                task_id=None,
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Standalone manager without event_bus initializes cleanly
    standalone_manager = SocketIOServerManager(
        socketio_server.app["config"], user_service, event_bus=None
    )
    assert standalone_manager.event_bus is None

    await socket_client.disconnect()


@pytest.mark.asyncio
async def test_socketio_summary_service_events_publish_digest_syn(
    socketio_server: TestServer,
    socket_client: SupernoteSocketClient,
) -> None:
    """Verify SummaryService tag, group, and summary mutations publish DIGEST-SYN Socket.IO notifications."""
    user_service: UserService = socketio_server.app["user_service"]
    summary_service: SummaryService = socketio_server.app["summary_service"]
    user_email = "test@example.com"
    user_id = await user_service.get_user_id(user_email)

    token = await user_service.create_session(user_email)
    await socket_client.connect(_make_handshake_params(token))

    async def _next_digest_msg() -> SocketDigestMessageData:
        msg = await asyncio.wait_for(anext(socket_client.messages()), timeout=2.0)
        assert isinstance(msg, SocketDigestMessageData)
        return msg

    # Tag create -> ADD_DIGEST (data_type='3')
    tag = await summary_service.add_tag(user_email, "Work")
    assert tag.id is not None
    msg = await _next_digest_msg()
    assert msg == SocketDigestMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.DIGEST_SYN,
        data=[
            DigestMessageTemplate(
                message_type=SocketIoAction.ADD_DIGEST,
                data_type=SocketIoDigestDataType.SUMMARY_TAG,
                equipment_no=None,
                id=tag.id,
                name="Work",
                unique_identifier=tag.unique_identifier,
                create_time=str(tag.created_at),
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Tag update -> UPDATE_DIGEST (data_type='3')
    await summary_service.update_tag(user_email, tag.id, "Personal")
    msg = await _next_digest_msg()
    assert msg == SocketDigestMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.DIGEST_SYN,
        data=[
            DigestMessageTemplate(
                message_type=SocketIoAction.UPDATE_DIGEST,
                data_type=SocketIoDigestDataType.SUMMARY_TAG,
                equipment_no=None,
                id=tag.id,
                name="Personal",
                unique_identifier=tag.unique_identifier,
                create_time=str(tag.created_at),
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Tag delete -> DELETE_DIGEST (data_type='3')
    await summary_service.delete_tag(user_email, tag.id)
    msg = await _next_digest_msg()
    assert msg == SocketDigestMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.DIGEST_SYN,
        data=[
            DigestMessageTemplate(
                message_type=SocketIoAction.DELETE_DIGEST,
                data_type=SocketIoDigestDataType.SUMMARY_TAG,
                equipment_no=None,
                id=tag.id,
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Summary group create -> ADD_DIGEST (data_type='1')
    group = await summary_service.add_group(
        user_email,
        AddSummaryGroupDTO(
            unique_identifier="grp-sock-1",
            name="Reading Notes",
            md5_hash="grp-md5-1",
            description="Books",
            creation_time=1700000001000,
            last_modified_time=1700000002000,
        ),
    )
    assert group.id is not None
    msg = await _next_digest_msg()
    assert msg == SocketDigestMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.DIGEST_SYN,
        data=[
            DigestMessageTemplate(
                message_type=SocketIoAction.ADD_DIGEST,
                data_type=SocketIoDigestDataType.SUMMARY_GROUP,
                equipment_no=None,
                id=group.id,
                name="Reading Notes",
                user_id=user_id,
                unique_identifier="grp-sock-1",
                is_summary_group="Y",
                description="Books",
                md5_hash="grp-md5-1",
                creation_time=1700000001000,
                last_modified_time=1700000002000,
                is_deleted="N",
                create_time=str(group.create_time),
                update_time=str(group.update_time),
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Summary group update -> UPDATE_DIGEST (data_type='1')
    await summary_service.update_group(
        user_email,
        UpdateSummaryGroupDTO(
            id=group.id,
            unique_identifier="grp-sock-1",
            name="Reading Notes Updated",
            md5_hash="grp-md5-2",
        ),
    )
    updated_group = await summary_service.get_summary(user_email, group.id)
    msg = await _next_digest_msg()
    assert msg == SocketDigestMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.DIGEST_SYN,
        data=[
            DigestMessageTemplate(
                message_type=SocketIoAction.UPDATE_DIGEST,
                data_type=SocketIoDigestDataType.SUMMARY_GROUP,
                equipment_no=None,
                id=group.id,
                name="Reading Notes Updated",
                user_id=user_id,
                unique_identifier="grp-sock-1",
                is_summary_group="Y",
                description="Books",
                md5_hash="grp-md5-2",
                creation_time=1700000001000,
                last_modified_time=1700000002000,
                is_deleted="N",
                create_time=str(updated_group.create_time),
                update_time=str(updated_group.update_time),
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Leaf summary create -> ADD_DIGEST (data_type='2')
    summary = await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=101,
            unique_identifier="sum-sock-1",
            parent_unique_identifier="grp-sock-1",
            content="Highlight text",
            source_path="/Note/Book.pdf",
            data_source="USER",
            source_type=1,
            tags="Work",
            md5_hash="sum-md5-1",
            metadata='{"page": 1}',
            comment_str="My comment",
            creation_time=1700000003000,
            last_modified_time=1700000004000,
            author="Author",
        ),
    )
    assert summary.id is not None
    msg = await _next_digest_msg()
    assert msg == SocketDigestMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.DIGEST_SYN,
        data=[
            DigestMessageTemplate(
                message_type=SocketIoAction.ADD_DIGEST,
                data_type=SocketIoDigestDataType.SUMMARY,
                equipment_no=None,
                id=summary.id,
                file_id=101,
                user_id=user_id,
                unique_identifier="sum-sock-1",
                parent_unique_identifier="grp-sock-1",
                content="Highlight text",
                source_path="/Note/Book.pdf",
                data_source="USER",
                source_type=1,
                is_summary_group="N",
                tags="Work",
                md5_hash="sum-md5-1",
                metadata='{"page": 1}',
                comment_str="My comment",
                creation_time=1700000003000,
                last_modified_time=1700000004000,
                is_deleted="N",
                create_time=str(summary.create_time),
                update_time=str(summary.update_time),
                timestamp=msg.data[0].timestamp,
                author="Author",
            )
        ],
    )

    # Leaf summary update -> UPDATE_DIGEST (data_type='2')
    await summary_service.update_summary(
        user_email,
        UpdateSummaryDTO(
            id=summary.id,
            content="Updated highlight text",
            md5_hash="sum-md5-2",
        ),
    )
    updated_summary = await summary_service.get_summary(user_email, summary.id)
    msg = await _next_digest_msg()
    assert msg == SocketDigestMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.DIGEST_SYN,
        data=[
            DigestMessageTemplate(
                message_type=SocketIoAction.UPDATE_DIGEST,
                data_type=SocketIoDigestDataType.SUMMARY,
                equipment_no=None,
                id=summary.id,
                file_id=101,
                user_id=user_id,
                unique_identifier="sum-sock-1",
                parent_unique_identifier="grp-sock-1",
                content="Updated highlight text",
                source_path="/Note/Book.pdf",
                data_source="USER",
                source_type=1,
                is_summary_group="N",
                tags="Work",
                md5_hash="sum-md5-2",
                metadata='{"page": 1}',
                comment_str="My comment",
                creation_time=1700000003000,
                last_modified_time=1700000004000,
                is_deleted="N",
                create_time=str(updated_summary.create_time),
                update_time=str(updated_summary.update_time),
                timestamp=msg.data[0].timestamp,
                author="Author",
            )
        ],
    )

    # Leaf summary delete -> DELETE_DIGEST (data_type='2')
    await summary_service.delete_summary(user_email, summary.id)
    msg = await _next_digest_msg()
    assert msg == SocketDigestMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.DIGEST_SYN,
        data=[
            DigestMessageTemplate(
                message_type=SocketIoAction.DELETE_DIGEST,
                data_type=SocketIoDigestDataType.SUMMARY,
                equipment_no=None,
                id=summary.id,
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Summary group delete -> DELETE_DIGEST (data_type='1')
    await summary_service.delete_group(user_email, group.id)
    msg = await _next_digest_msg()
    assert msg == SocketDigestMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.DIGEST_SYN,
        data=[
            DigestMessageTemplate(
                message_type=SocketIoAction.DELETE_DIGEST,
                data_type=SocketIoDigestDataType.SUMMARY_GROUP,
                equipment_no=None,
                id=group.id,
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    await socket_client.disconnect()


@pytest.mark.asyncio
async def test_socketio_file_service_events_publish_file_syn(
    socketio_server: TestServer,
    socket_client: SupernoteSocketClient,
) -> None:
    """Verify FileService folder and file mutations publish FILE-SYN Socket.IO notifications."""
    user_service: UserService = socketio_server.app["user_service"]
    file_service: FileService = socketio_server.app["file_service"]
    blob_storage: BlobStorage = socketio_server.app["blob_storage"]
    user_email = "test@example.com"

    token = await user_service.create_session(user_email)
    await socket_client.connect(_make_handshake_params(token))

    async def _next_file_msg() -> SocketMessageData:
        msg = await asyncio.wait_for(anext(socket_client.messages()), timeout=2.0)
        assert isinstance(msg, SocketMessageData)
        return msg

    # Folder create at root -> ADDFOLDER ('FOLDE', original_path='')
    folder_a = await file_service.create_directory_by_id(user_email, 0, "FolderA")
    msg = await _next_file_msg()
    assert msg == SocketMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.FILE_SYN,
        data=[
            SocketIoMessageTemplate(
                message_type=SocketIoAction.ADDFOLDER,
                equipment_no=None,
                file_type=SocketIoFileType.FOLDER,
                id=folder_a.id,
                original_name="FolderA",
                new_name="FolderA",
                md5=None,
                size=0,
                directory_id=0,
                go_directory_id=None,
                original_path="",
                new_path="",
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Nested folder create -> ADDFOLDER ('FOLDE', original_path='FolderA/')
    folder_b = await file_service.create_directory_by_id(
        user_email, folder_a.id, "SubB"
    )
    msg = await _next_file_msg()
    assert msg == SocketMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.FILE_SYN,
        data=[
            SocketIoMessageTemplate(
                message_type=SocketIoAction.ADDFOLDER,
                equipment_no=None,
                file_type=SocketIoFileType.FOLDER,
                id=folder_b.id,
                original_name="SubB",
                new_name="SubB",
                md5=None,
                size=0,
                directory_id=folder_a.id,
                go_directory_id=None,
                original_path="FolderA/",
                new_path="FolderA/",
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # File upload finish -> DOWNLOADFILE ('FILE', original_path='FolderA/')
    payload = b"hello supernote socket"
    md5 = hashlib.md5(payload).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "sock_blob_1", payload)
    file_item = await file_service.finish_upload(
        user_email, "notes.pdf", "/FolderA", md5, "sock_blob_1"
    )
    msg = await _next_file_msg()
    assert msg == SocketMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.FILE_SYN,
        data=[
            SocketIoMessageTemplate(
                message_type=SocketIoAction.ADDFILE,
                equipment_no=None,
                file_type=SocketIoFileType.FILE,
                id=file_item.id,
                original_name="notes.pdf",
                new_name="notes.pdf",
                md5=md5,
                size=len(payload),
                directory_id=folder_a.id,
                go_directory_id=None,
                original_path="FolderA/",
                new_path="FolderA/",
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Rename file in-place -> MODIFYFILE ('FILE')
    await file_service.rename_item(user_email, file_item.id, "notes_v2.pdf")
    msg = await _next_file_msg()
    assert msg == SocketMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.FILE_SYN,
        data=[
            SocketIoMessageTemplate(
                message_type=SocketIoAction.MODIFYFILE,
                equipment_no=None,
                file_type=SocketIoFileType.FILE,
                id=file_item.id,
                original_name="notes.pdf",
                new_name="notes_v2.pdf",
                md5=md5,
                size=len(payload),
                directory_id=folder_a.id,
                go_directory_id=None,
                original_path="FolderA/",
                new_path="FolderA/",
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Rename folder in-place -> MODIFYFOLDER ('FOLDE')
    await file_service.rename_item(user_email, folder_b.id, "SubB_Renamed")
    msg = await _next_file_msg()
    assert msg == SocketMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.FILE_SYN,
        data=[
            SocketIoMessageTemplate(
                message_type=SocketIoAction.MODIFYFOLDER,
                equipment_no=None,
                file_type=SocketIoFileType.FOLDER,
                id=folder_b.id,
                original_name="SubB",
                new_name="SubB_Renamed",
                md5=None,
                size=0,
                directory_id=folder_a.id,
                go_directory_id=None,
                original_path="FolderA/",
                new_path="FolderA/",
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Move file across directories -> MOVEFILE ('FILE')
    await file_service.move_item(
        user_email,
        file_item.id,
        "/FolderA/SubB_Renamed/notes_v2.pdf",
        autorename=False,
    )
    msg = await _next_file_msg()
    assert msg == SocketMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.FILE_SYN,
        data=[
            SocketIoMessageTemplate(
                message_type=SocketIoAction.MOVEFILE,
                equipment_no=None,
                file_type=SocketIoFileType.FILE,
                id=file_item.id,
                original_name="notes_v2.pdf",
                new_name="notes_v2.pdf",
                md5=md5,
                size=len(payload),
                directory_id=folder_b.id,
                go_directory_id=folder_b.id,
                original_path="FolderA/",
                new_path="FolderA/SubB_Renamed/",
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Move folder across directories -> MOVEFOLDER ('FOLDE')
    await file_service.move_item(
        user_email, folder_b.id, "/SubB_Root", autorename=False
    )
    msg = await _next_file_msg()
    assert msg == SocketMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.FILE_SYN,
        data=[
            SocketIoMessageTemplate(
                message_type=SocketIoAction.MOVEFOLDER,
                equipment_no=None,
                file_type=SocketIoFileType.FOLDER,
                id=folder_b.id,
                original_name="SubB_Renamed",
                new_name="SubB_Root",
                md5=None,
                size=0,
                directory_id=0,
                go_directory_id=None,
                original_path="FolderA/",
                new_path="",
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Copy file -> COPYFILE ('FILE')
    copied_file = await file_service.copy_item(
        user_email,
        file_item.id,
        to_path="/FolderA/notes_copy.pdf",
        autorename=True,
    )
    msg = await _next_file_msg()
    assert msg == SocketMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.FILE_SYN,
        data=[
            SocketIoMessageTemplate(
                message_type=SocketIoAction.COPYFILE,
                equipment_no=None,
                file_type=SocketIoFileType.FILE,
                id=file_item.id,
                new_id=copied_file.id,
                original_name="notes_v2.pdf",
                new_name="notes_copy.pdf",
                md5=md5,
                size=len(payload),
                directory_id=folder_b.id,
                go_directory_id=folder_a.id,
                original_path="SubB_Root/",
                new_path="FolderA/",
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Copy folder -> COPYFOLDER ('FOLDE')
    copied_folder = await file_service.copy_item(
        user_email,
        folder_b.id,
        to_path="/FolderA/SubB_Copy",
        autorename=True,
    )
    msg = await _next_file_msg()
    assert msg == SocketMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.FILE_SYN,
        data=[
            SocketIoMessageTemplate(
                message_type=SocketIoAction.COPYFOLDER,
                equipment_no=None,
                file_type=SocketIoFileType.FOLDER,
                id=folder_b.id,
                new_id=copied_folder.id,
                original_name="SubB_Root",
                new_name="SubB_Copy",
                md5=None,
                size=0,
                directory_id=0,
                go_directory_id=folder_a.id,
                original_path="",
                new_path="FolderA/",
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Delete file -> DELETEFILE ('FILE')
    await file_service.delete_item(user_email, copied_file.id)
    msg = await _next_file_msg()
    assert msg == SocketMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.FILE_SYN,
        data=[
            SocketIoMessageTemplate(
                message_type=SocketIoAction.DELETEFILE,
                equipment_no=None,
                file_type=SocketIoFileType.FILE,
                id=copied_file.id,
                original_name="notes_copy.pdf",
                new_name=None,
                md5=md5,
                size=len(payload),
                directory_id=folder_a.id,
                go_directory_id=None,
                original_path="FolderA/",
                new_path=None,
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Delete folder -> DELETEFOLDER ('FOLDE')
    await file_service.delete_item(user_email, copied_folder.id)
    msg = await _next_file_msg()
    assert msg == SocketMessageData(
        code="200",
        msg="Success",
        timestamp=msg.timestamp,
        msg_type=SocketIoMessageType.FILE_SYN,
        data=[
            SocketIoMessageTemplate(
                message_type=SocketIoAction.DELETEFOLDER,
                equipment_no=None,
                file_type=SocketIoFileType.FOLDER,
                id=copied_folder.id,
                original_name="SubB_Copy",
                new_name=None,
                md5=None,
                size=0,
                directory_id=folder_a.id,
                go_directory_id=None,
                original_path="FolderA/",
                new_path=None,
                timestamp=msg.data[0].timestamp,
            )
        ],
    )

    # Restore file and folder from recycle bin -> DOWNLOADFILE and ADDFOLDER
    recycled = await file_service.list_recycle(user_email)
    recycle_file = next(r for r in recycled if r.name == "notes_copy.pdf")
    recycle_folder = next(r for r in recycled if r.name == "SubB_Copy")
    await file_service.revert_from_recycle(user_email, [recycle_file.id])
    msg_restored_file = await _next_file_msg()
    assert msg_restored_file == SocketMessageData(
        code="200",
        msg="Success",
        timestamp=msg_restored_file.timestamp,
        msg_type=SocketIoMessageType.FILE_SYN,
        data=[
            SocketIoMessageTemplate(
                message_type=SocketIoAction.ADDFILE,
                equipment_no=None,
                file_type=SocketIoFileType.FILE,
                id=copied_file.id,
                original_name="notes_copy.pdf",
                new_name="notes_copy.pdf",
                md5=md5,
                size=len(payload),
                directory_id=folder_a.id,
                go_directory_id=None,
                original_path="FolderA/",
                new_path="FolderA/",
                timestamp=msg_restored_file.data[0].timestamp,
            )
        ],
    )
    await file_service.revert_from_recycle(user_email, [recycle_folder.id])
    msg_restored_folder = await _next_file_msg()
    assert msg_restored_folder == SocketMessageData(
        code="200",
        msg="Success",
        timestamp=msg_restored_folder.timestamp,
        msg_type=SocketIoMessageType.FILE_SYN,
        data=[
            SocketIoMessageTemplate(
                message_type=SocketIoAction.ADDFOLDER,
                equipment_no=None,
                file_type=SocketIoFileType.FOLDER,
                id=copied_folder.id,
                original_name="SubB_Copy",
                new_name="SubB_Copy",
                md5=None,
                size=0,
                directory_id=folder_a.id,
                go_directory_id=None,
                original_path="FolderA/",
                new_path="FolderA/",
                timestamp=msg_restored_folder.data[0].timestamp,
            )
        ],
    )

    await socket_client.disconnect()


@pytest.mark.asyncio
async def test_socketio_eio3_device_handshake_and_ping_compat(
    socketio_server: TestServer,
) -> None:
    """Verify real Supernote device EIO=3 (Socket.IO v2) WebSocket handshake, ACKs, and client PING/PONG."""
    user_service: UserService = socketio_server.app["user_service"]
    manager: SocketIOServerManager = socketio_server.app["socketio_manager"]
    user_email = "test@example.com"
    user_id = await user_service.get_user_id(user_email)

    token = await user_service.create_session(user_email)
    params = _make_handshake_params(token)

    def _ws_url(p: SocketHandshakeParams) -> str:
        return (
            f"http://{socketio_server.host}:{socketio_server.port}/socket.io/"
            f"?EIO=3&transport=websocket"
            f"&token={p.token}&type={p.type}"
            f"&random={p.random}&sign={p.sign}"
        )

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(_ws_url(params)) as ws:
            # Server sends Engine.IO OPEN ('0{...}') followed immediately by
            # Socket.IO default-namespace CONNECT ('40{...}') without waiting
            # for a client '40' packet.
            eio_open = await asyncio.wait_for(ws.receive_str(), timeout=2.0)
            assert eio_open.startswith("0{")

            sio_connect = await asyncio.wait_for(ws.receive_str(), timeout=2.0)
            assert sio_connect.startswith("40")

            # Duplicate Socket.IO default-namespace CONNECT ('40') from client is ignored
            await ws.send_str("40")

            # Client-initiated Engine.IO v3 PING ('2') receives PONG ('3')
            await ws.send_str("2")
            eio_pong = await asyncio.wait_for(ws.receive_str(), timeout=2.0)
            assert eio_pong == "3"

            # Client ACKs and unhandled payloads on to-do and digest channels
            await ws.send_str('42["to-do","Received"]')
            await ws.send_str('42["to-do","other"]')
            await ws.send_str('42["digest","Received"]')
            await ws.send_str('42["digest","other"]')
            await ws.send_str("2")
            assert await asyncio.wait_for(ws.receive_str(), timeout=2.0) == "3"

            # Server-to-device notification is delivered over the default namespace
            msg_data = SocketMessageData(
                code="0",
                msg="eio3 sync notification",
                timestamp=1700000000000,
                msg_type=SocketIoMessageType.FILE_SYN,
            )
            await manager.send_message(user_id, msg_data)
            event_frame = await asyncio.wait_for(ws.receive_str(), timeout=2.0)
            assert event_frame.startswith('42["ServerMessage",')
            assert "eio3 sync notification" in event_frame

            # Revoking the session causes subsequent to-do ACK to return 403 error and disconnect
            await user_service.logout(token)
            await ws.send_str('42["to-do","Received"]')
            err_frame = await asyncio.wait_for(ws.receive_str(), timeout=2.0)
            assert err_frame.startswith('42["ServerMessage",')
            assert "token verification failed" in err_frame

        # Also verify revoked session on digest ACK channel
        token2 = await user_service.create_session(user_email)
        async with session.ws_connect(_ws_url(_make_handshake_params(token2))) as ws2:
            await asyncio.wait_for(ws2.receive_str(), timeout=2.0)
            await asyncio.wait_for(ws2.receive_str(), timeout=2.0)
            await user_service.logout(token2)
            await ws2.send_str('42["digest","Received"]')
            err_frame2 = await asyncio.wait_for(ws2.receive_str(), timeout=2.0)
            assert err_frame2.startswith('42["ServerMessage",')
            assert "token verification failed" in err_frame2


@pytest.mark.asyncio
async def test_socketio_client_channels_and_error_handling_via_server(
    socketio_server: TestServer,
    socket_client: SupernoteSocketClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify SupernoteSocketClient handles TASK-SYN, DIGEST-SYN, malformed payloads, and unexpected server replies."""
    user_service: UserService = socketio_server.app["user_service"]
    manager: SocketIOServerManager = socketio_server.app["socketio_manager"]
    user_email = "test@example.com"
    user_id = await user_service.get_user_id(user_email)

    token = await user_service.create_session(user_email)
    await socket_client.connect(_make_handshake_params(token))

    # Valid TASK-SYN and DIGEST-SYN envelopes delivered through server
    task_msg = SocketTaskMessageData(
        code="200",
        msg="Success",
        timestamp=1700000001000,
        data=[
            ScheduleMessageTemplate(
                message_type=SocketIoAction.QUERY,
                task_list_id="list-1",
                task_id="task-1",
                timestamp=1700000001000,
            )
        ],
    )
    await manager.send_message(user_id, task_msg)
    assert await anext(socket_client.messages()) == task_msg

    digest_msg = SocketDigestMessageData(
        code="200",
        msg="Success",
        timestamp=1700000002000,
        data=[
            DigestMessageTemplate(
                message_type=SocketIoAction.ADD_DIGEST,
                data_type=SocketIoDigestDataType.SUMMARY_TAG,
                id=10,
                name="Tag",
                timestamp=1700000002000,
            )
        ],
    )
    await manager.send_message(user_id, digest_msg)
    assert await anext(socket_client.messages()) == digest_msg

    # Malformed payloads emitted by server on to-do and digest channels log warnings without crashing
    await manager.sio.emit(
        SocketIoEvent.TODO.value, "{not-valid-json", room=f"user_{user_id}"
    )
    await manager.sio.emit(
        SocketIoEvent.DIGEST.value, "{not-valid-json", room=f"user_{user_id}"
    )

    # Unexpected ping reply payload logs a warning
    await manager.sio.emit(
        SocketIoEvent.RATTA_PING.value, "unexpected-pong", room=f"user_{user_id}"
    )
    await socket_client.ping(timeout=1.0)
    assert "Unexpected ping reply payload: unexpected-pong" in caplog.text
    assert "Failed to parse to-do message" in caplog.text
    assert "Failed to parse digest message" in caplog.text

    # Non-'true' plain-string ServerMessage causes check_status to raise SupernoteSocketError
    await manager.sio.emit(
        SocketIoEvent.SERVER_MESSAGE.value, "false", room=f"user_{user_id}"
    )
    with pytest.raises(SupernoteSocketError, match="Unexpected status check reply"):
        await socket_client.check_status(timeout=1.0)

    await socket_client.disconnect()


@pytest.mark.asyncio
async def test_socketio_ratta_ping_without_payload(
    socketio_server: TestServer,
) -> None:
    """Devices emit `ratta_ping` and `ClientMessage` with no arguments or extra positional args."""
    user_service: UserService = socketio_server.app["user_service"]
    user_id = "test@example.com"
    token = await user_service.create_session(user_id)
    params = _make_handshake_params(token)

    url = (
        f"http://{socketio_server.host}:{socketio_server.port}/socket.io/"
        f"?EIO=4&transport=websocket&token={params.token}&sign={params.sign}"
        f"&random={params.random}&type={params.type}"
    )

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url) as ws:
            assert (await ws.receive_str()).startswith("0{")
            await ws.send_str("40")
            assert (await ws.receive_str()).startswith("40")

            await ws.send_str('42["ratta_ping"]')
            assert await ws.receive_str() == '42["ratta_ping","Received"]'

            await ws.send_str('42["ratta_ping","extra1","extra2"]')
            assert await ws.receive_str() == '42["ratta_ping","Received"]'

            await ws.send_str('42["ClientMessage"]')

            await ws.send_str('42["ClientMessage","status","extra1"]')
            assert await ws.receive_str() == '42["ServerMessage","true"]'
