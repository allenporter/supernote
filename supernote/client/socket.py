"""Async Socket.IO client (`SupernoteSocketClient`) for real-time Supernote events.

This module implements `supernote.client.socket.SupernoteSocketClient`, which connects to the
server's `/socket.io` namespace using signed handshake parameters (`SocketHandshakeParams`),
supports active heartbeat checks (`ping`, `check_status`), and yields real-time `FILE-SYN`,
`TASK-SYN`, and `DIGEST-SYN` push notifications via the `messages()` async iterator. Event models
are defined in `supernote.models.socket`; see `supernote.client` for usage examples.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import socketio

from supernote.client.exceptions import SupernoteSocketError
from supernote.models.socket import (
    SocketDigestMessageData,
    SocketHandshakeParams,
    SocketIoClientMessage,
    SocketIoEvent,
    SocketMessageData,
    SocketTaskMessageData,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT: float = 5.0
"""Default timeout in seconds for Socket.IO request/response operations."""


class SupernoteSocketClient:
    """Async Socket.IO client for interacting with the Supernote real-time server."""

    def __init__(self, host: str) -> None:
        self.host = host.rstrip("/")
        self._sio = socketio.AsyncClient()
        self._message_queue: asyncio.Queue[
            SocketMessageData | SocketTaskMessageData | SocketDigestMessageData
        ] = asyncio.Queue()
        self._status_queue: asyncio.Queue[str] = asyncio.Queue()
        self._ping_queue: asyncio.Queue[str] = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._connected = False

        self._setup_event_handlers()

    def _setup_event_handlers(self) -> None:
        @self._sio.event
        async def connect() -> None:
            logger.debug("Socket.IO client connected to %s", self.host)
            self._connected = True

        @self._sio.event
        async def disconnect() -> None:
            logger.debug("Socket.IO client disconnected")
            self._connected = False

        @self._sio.on(SocketIoEvent.SERVER_MESSAGE.value)
        async def on_server_message(data: str) -> None:
            logger.debug("Received ServerMessage: %s", data)
            if isinstance(data, str):
                try:
                    msg = SocketMessageData.from_json(data)
                    await self._message_queue.put(msg)
                    return
                except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                    pass
            await self._status_queue.put(data)

        @self._sio.on(SocketIoEvent.TODO.value)
        async def on_todo_message(data: str) -> None:
            logger.debug("Received to-do: %s", data)
            if isinstance(data, str):
                try:
                    msg = SocketTaskMessageData.from_json(data)
                    await self._message_queue.put(msg)
                except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                    logger.warning("Failed to parse to-do message: %s", data)

        @self._sio.on(SocketIoEvent.DIGEST.value)
        async def on_digest_message(data: str) -> None:
            logger.debug("Received digest: %s", data)
            if isinstance(data, str):
                try:
                    msg = SocketDigestMessageData.from_json(data)
                    await self._message_queue.put(msg)
                except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                    logger.warning("Failed to parse digest message: %s", data)

        @self._sio.on(SocketIoEvent.RATTA_PING.value)
        async def on_ratta_ping(data: Any) -> None:
            logger.debug("Received ratta_ping: %s", data)
            await self._ping_queue.put(str(data))

    @property
    def is_connected(self) -> bool:
        """Return True if the client is currently connected."""
        return self._connected

    async def connect(self, params: SocketHandshakeParams) -> None:
        """Connect to the Supernote Socket.IO server using handshake authentication parameters.

        Args:
            params: Handshake authentication parameters containing token, type, random, and sign.
        """
        query_string = (
            f"token={params.token}"
            f"&type={params.type}"
            f"&random={params.random}"
            f"&sign={params.sign}"
        )

        url = f"{self.host}/?{query_string}"
        logger.debug("Connecting to Socket.IO server at %s", url)
        await self._sio.connect(
            url,
            socketio_path="socket.io",
            transports=["polling", "websocket"],
            wait_timeout=10,
        )

    async def disconnect(self) -> None:
        """Disconnect from the Socket.IO server."""
        if self._connected:
            await self._sio.disconnect()
            self._connected = False

    async def ping(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Send a ratta_ping heartbeat request to the server and verify response.

        Args:
            timeout: Seconds to wait before raising TimeoutError.

        Raises:
            TimeoutError: If the server does not respond within timeout seconds.
        """
        async with self._lock:
            await self._sio.emit(SocketIoEvent.RATTA_PING.value, "ping")
            reply = await asyncio.wait_for(self._ping_queue.get(), timeout=timeout)
            if reply != SocketIoClientMessage.RECEIVED.value:
                logger.warning("Unexpected ping reply payload: %s", reply)

    async def check_status(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Send a status heartbeat request to the server and verify response.

        Args:
            timeout: Seconds to wait before raising TimeoutError.

        Raises:
            TimeoutError: If the server does not respond within timeout seconds.
            SupernoteSocketError: If the server responds with an error or non-'true' payload.
        """
        async with self._lock:
            await self._sio.emit(
                SocketIoEvent.CLIENT_MESSAGE.value,
                SocketIoClientMessage.STATUS.value,
            )
            res = await asyncio.wait_for(self._status_queue.get(), timeout=timeout)
            if res != "true":
                raise SupernoteSocketError(f"Unexpected status check reply: {res}")

    async def send_client_message(self, message: str) -> None:
        """Send a custom ClientMessage string payload to the server without waiting for response."""
        await self._sio.emit(SocketIoEvent.CLIENT_MESSAGE.value, message)

    async def messages(
        self,
    ) -> AsyncIterator[
        SocketMessageData | SocketTaskMessageData | SocketDigestMessageData
    ]:
        """Stream incoming Socket.IO sync events continuously as an async iterator.

        Yields:
            Parsed SocketMessageData, SocketTaskMessageData, or SocketDigestMessageData objects emitted by the server.
        """
        while self._connected or not self._message_queue.empty():
            yield await self._message_queue.get()
