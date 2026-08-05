"""Socket.IO client for Supernote real-time communication."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

socketio: Any = None
try:
    import socketio
except ImportError:
    pass

from supernote.client.exceptions import SupernoteSocketError  # noqa: E402
from supernote.models.socket import (  # noqa: E402
    SocketHandshakeParams,
    SocketIoClientMessage,
    SocketIoEvent,
    SocketMessageData,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT: float = 5.0
"""Default timeout in seconds for Socket.IO request/response operations."""


class SupernoteSocketClient:
    """Async Socket.IO client for interacting with the Supernote real-time server."""

    def __init__(self, host: str) -> None:
        if socketio is None:
            raise SupernoteSocketError(
                "python-socketio is required for SupernoteSocketClient. "
                "Install supernote with client extras: pip install supernote[client]"
            )
        self.host = host.rstrip("/")
        self._sio = socketio.AsyncClient()
        self._message_queue: asyncio.Queue[SocketMessageData] = asyncio.Queue()
        self._status_queue: asyncio.Queue[str | SocketMessageData] = asyncio.Queue()
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

        async def _do_ping() -> None:
            async with self._lock:
                await self._sio.emit(SocketIoEvent.RATTA_PING.value, "ping")
                reply = await asyncio.wait_for(self._ping_queue.get(), timeout=timeout)
                if reply != SocketIoClientMessage.RECEIVED.value:
                    logger.warning("Unexpected ping reply payload: %s", reply)

        await asyncio.wait_for(_do_ping(), timeout=timeout)

    async def check_status(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Send a status heartbeat request to the server and verify response.

        Args:
            timeout: Seconds to wait before raising TimeoutError.

        Raises:
            TimeoutError: If the server does not respond within timeout seconds.
            SupernoteSocketError: If the server responds with an error or non-'true' payload.
        """

        async def _do_check() -> None:
            async with self._lock:
                await self._sio.emit(
                    SocketIoEvent.CLIENT_MESSAGE.value,
                    SocketIoClientMessage.STATUS.value,
                )
                res = await asyncio.wait_for(self._status_queue.get(), timeout=timeout)
                if res != "true":
                    if isinstance(res, SocketMessageData):
                        raise SupernoteSocketError(
                            f"Server status check failed: code={res.code}, msg={res.msg}"
                        )
                    raise SupernoteSocketError(f"Unexpected status check reply: {res}")

        await asyncio.wait_for(_do_check(), timeout=timeout)

    async def send_client_message(self, message: str) -> None:
        """Send a custom ClientMessage string payload to the server without waiting for response."""
        await self._sio.emit(SocketIoEvent.CLIENT_MESSAGE.value, message)

    async def messages(self) -> AsyncIterator[SocketMessageData]:
        """Stream incoming SocketMessageData sync events continuously as an async iterator.

        Yields:
            Parsed SocketMessageData objects emitted by the server.
        """
        while self._connected or not self._message_queue.empty():
            yield await self._message_queue.get()
