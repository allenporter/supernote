"""Tests for the device realtime (Engine.IO-v3 / Socket.IO-v2) socket.io endpoint."""

import json

import pytest
from aiohttp import WSServerHandshakeError
from aiohttp.test_utils import TestClient


async def test_socketio_connect_handshake(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """A valid device connection gets the EIO OPEN + server-initiated SIO CONNECT.

    The device (Engine.IO v3 / Socket.IO v2) goes straight to transport=websocket and
    idles until the server initiates the namespace CONNECT. Without this endpoint the
    websocket 500'd on the ASGI catch-all and the device aborted its sync
    ("App Data Sync Failed").
    """
    token = auth_headers["x-access-token"]
    ws = await client.ws_connect(
        f"/socket.io/?EIO=3&transport=websocket&type=SN078D10010247&token={token}"
    )
    try:
        # 1) Engine.IO OPEN handshake with a session id + ping timings.
        open_frame = await ws.receive_str()
        assert open_frame.startswith("0")
        payload = json.loads(open_frame[1:])
        assert payload["sid"]
        assert payload["pingInterval"] == 25000
        assert payload["pingTimeout"] == 60000

        # 2) Server-initiated Socket.IO v2 CONNECT for the default namespace.
        assert await ws.receive_str() == "40"

        # 3) Engine.IO PING from the client is answered with a PONG (keepalive).
        await ws.send_str("2")
        assert await ws.receive_str() == "3"
    finally:
        await ws.close()


async def test_socketio_echoes_client_namespace_connect(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """A client-initiated namespace CONNECT is echoed so the client fires 'connect'."""
    token = auth_headers["x-access-token"]
    ws = await client.ws_connect(f"/socket.io/?token={token}")
    try:
        await ws.receive_str()  # OPEN
        await ws.receive_str()  # server CONNECT "40"
        # Client opens a custom namespace via MESSAGE(4)+CONNECT(0).
        await ws.send_str("40/device,")
        assert await ws.receive_str() == "40/device,"
    finally:
        await ws.close()


async def test_socketio_requires_websocket_transport(client: TestClient) -> None:
    """A plain GET (no Upgrade) is rejected — the device only uses websocket."""
    resp = await client.get("/socket.io/")
    assert resp.status == 400


async def test_socketio_rejects_missing_token(client: TestClient) -> None:
    """An upgrade with no token is rejected 401 (the channel is authenticated)."""
    resp = await client.get(
        "/socket.io/",
        headers={
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
            "Sec-WebSocket-Version": "13",
        },
    )
    assert resp.status == 401


async def test_socketio_rejects_invalid_token(client: TestClient) -> None:
    """An upgrade with a bogus token is rejected at the handshake (401)."""
    with pytest.raises(WSServerHandshakeError) as exc:
        await client.ws_connect("/socket.io/?token=not-a-real-token")
    assert exc.value.status == 401
