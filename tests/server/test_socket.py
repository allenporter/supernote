"""Integration tests for Socket.IO server handler and client interaction."""

import asyncio
import hashlib
from collections.abc import AsyncGenerator, Callable

import jwt
import pytest
from aiohttp.test_utils import TestServer
from socketio.exceptions import ConnectionError as SocketIOConnectionError

from supernote.client.socket import SupernoteSocketClient
from supernote.models.socket import (
    SocketHandshakeParams,
    SocketIoAction,
    SocketIoMessageTemplate,
    SocketIoMessageType,
    SocketMessageData,
)
from supernote.server.app import create_app
from supernote.server.config import ServerConfig
from supernote.server.services.user import JWT_ALGORITHM
from supernote.server.socket import SocketIOServerManager


def _make_handshake_params(
    token: str, conn_type: str = "file", random_val: str = "12345"
) -> SocketHandshakeParams:
    raw = f"{token}_{conn_type}_{random_val}"
    sign = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return SocketHandshakeParams(
        token=token,
        type=conn_type,
        random=random_val,
        sign=sign,
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
    socket_client: SupernoteSocketClient,
    server_config: ServerConfig,
) -> None:
    secret = server_config.auth.secret_key
    token_a = jwt.encode({"sub": "test@example.com"}, secret, algorithm=JWT_ALGORITHM)
    params_a = _make_handshake_params(token_a)

    await socket_client.connect(params_a)
    assert socket_client.is_connected

    # Send ratta_ping and verify success
    await socket_client.ping(timeout=5.0)

    await socket_client.disconnect()
    assert not socket_client.is_connected


@pytest.mark.asyncio
async def test_socketio_status_heartbeat(
    socket_client: SupernoteSocketClient,
    server_config: ServerConfig,
) -> None:
    secret = server_config.auth.secret_key
    token_a = jwt.encode({"sub": "test@example.com"}, secret, algorithm=JWT_ALGORITHM)
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
    server_config: ServerConfig,
    create_test_user: None,
) -> None:
    secret = server_config.auth.secret_key
    user_a = "test@example.com"
    user_b = "a@example.com"

    token_a = jwt.encode({"sub": user_a}, secret, algorithm=JWT_ALGORITHM)
    token_b = jwt.encode({"sub": user_b}, secret, algorithm=JWT_ALGORITHM)

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
        code="0",
        msg="update notification",
        timestamp=1700000000000,
        msg_type=SocketIoMessageType.FILE_SYN,
        data=[
            SocketIoMessageTemplate(
                message_type=SocketIoAction.ADDFILE,
                equipment_no="SN123",
                file_type="note",
                id=101,
                original_name="NoteA.note",
            )
        ],
    )

    await manager.send_message(user_a, msg_data_a)

    # User A receives the targeted message
    received_a = await anext(client_a.messages())
    assert isinstance(received_a, SocketMessageData)
    assert received_a.code == "0"
    assert len(received_a.data) == 1
    assert received_a.data[0].original_name == "NoteA.note"

    # User B should not receive any message
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(client_b.messages()), timeout=1.0)

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
) -> None:
    # Valid signature but invalid JWT token string
    invalid_token_params = _make_handshake_params("bad.jwt.token")

    with pytest.raises(SocketIOConnectionError):
        await socket_client.connect(invalid_token_params)

    assert not socket_client.is_connected


@pytest.mark.asyncio
async def test_socketio_client_received_ack(
    socket_client: SupernoteSocketClient,
    server_config: ServerConfig,
) -> None:
    secret = server_config.auth.secret_key
    token_a = jwt.encode({"sub": "test@example.com"}, secret, algorithm=JWT_ALGORITHM)
    params_a = _make_handshake_params(token_a)

    await socket_client.connect(params_a)
    assert socket_client.is_connected

    # Send client delivery ACK
    await socket_client.send_client_message("Received")

    await socket_client.disconnect()


@pytest.mark.asyncio
async def test_socketio_client_messages_async_iterator(
    socketio_server: TestServer,
    socket_client: SupernoteSocketClient,
    server_config: ServerConfig,
) -> None:
    secret = server_config.auth.secret_key
    user_id = "test@example.com"
    token_a = jwt.encode({"sub": user_id}, secret, algorithm=JWT_ALGORITHM)
    params_a = _make_handshake_params(token_a)

    await socket_client.connect(params_a)

    manager: SocketIOServerManager = socketio_server.app["socketio_manager"]
    msg_data = SocketMessageData(
        code="0",
        msg="test message",
        timestamp=1700000000000,
        msg_type=SocketIoMessageType.FILE_SYN,
    )
    await manager.send_message(user_id, msg_data)

    async for msg in socket_client.messages():
        assert isinstance(msg, SocketMessageData)
        assert msg.msg == "test message"
        break

    await socket_client.disconnect()
