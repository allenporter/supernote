"""Realtime socket.io endpoint for the Supernote device's app-data channel.

The device opens a realtime channel on every sync with:

    GET /socket.io/?sign=..&random=..&EIO=3&transport=websocket&type=<deviceId>&token=<jwt>

i.e. **Engine.IO protocol v3 / Socket.IO protocol v2**, going straight to
``transport=websocket`` (no polling-first upgrade). Without an endpoint here the
websocket falls through to the MCP/auth ``ASGIResource`` catch-all, whose aiohttp_asgi
bridge raises on the websocket-close ASGI message -> 500; the device retries, aborts the
whole sync, and shows "App Data Sync Failed".

This hand-rolls just enough EIO3/SIO2 to make the device **connect cleanly** and keep the
channel alive. That is sufficient: the device's "App Data Sync Failed" was a downstream
symptom of the sync aborting on that 500 — once the channel connects (and the planner /
summary REST calls succeed), the device completes its app-data sync over this connected
channel with no further server-initiated events required (established live on device
SN078D10010247, wayfinder zero-banner-sync tickets 01/04).

It is dependency-free on purpose: modern ``python-socketio`` / ``python-engineio``
(v5 / v4) hard-reject ``EIO=3`` with a 400 and have removed the EIO3 encoding paths, so
the library route would need an old (<5 / <4) pin. Hand-rolling over aiohttp's native
``WebSocketResponse`` avoids the dependency.

Wire-format (text frames over the single websocket)::

    packet = <engineio_type><payload>
    engineio types : 0 open  1 close  2 ping  3 pong  4 message  5 upgrade  6 noop
    a Socket.IO packet rides inside an engineio MESSAGE(4):
        socketio types : 0 CONNECT 1 DISCONNECT 2 EVENT 3 ACK 4 ERROR ...
    so on the wire:
        "0{...}"    engineio OPEN    (handshake, server -> client)
        "40"        MESSAGE+CONNECT  (default-namespace connect)
        "2" / "3"   engineio ping / pong  (EIO3: CLIENT pings, server pongs)
"""

from __future__ import annotations

import json
import logging
import secrets

from aiohttp import WSMsgType, web

from .routes.decorators import public_route

logger = logging.getLogger(__name__)

# EIO3 handshake timings advertised to the client (milliseconds).
_PING_INTERVAL_MS = 25000
_PING_TIMEOUT_MS = 60000


@public_route  # bypass jwt_auth_middleware; the device carries its token as a query param
async def handle_socketio(request: web.Request) -> web.StreamResponse:
    """Serve the device's Engine.IO-v3 / Socket.IO-v2 realtime channel (connect-only)."""
    if request.headers.get("Upgrade", "").lower() != "websocket":
        # The device only ever uses transport=websocket; nothing else to serve.
        return web.json_response({"error": "websocket transport required"}, status=400)

    # The device authenticates this channel with its JWT as a query param (not the
    # x-access-token header the REST middleware reads), so verify it here and reject
    # unauthenticated connections.
    token = request.query.get("token")
    if not token:
        return web.json_response({"error": "token required"}, status=401)
    try:
        session = await request.app["user_service"].verify_token(token)
    except Exception:
        session = None
    if not session:
        return web.json_response({"error": "invalid token"}, status=401)

    ws = web.WebSocketResponse(protocols=("websocket",), heartbeat=None)
    await ws.prepare(request)

    sid = secrets.token_hex(12)
    device = request.query.get("type")
    logger.info("socket.io channel open: device=%s sid=%s", device, sid)

    # 1) Engine.IO OPEN handshake.
    await ws.send_str(
        "0"
        + json.dumps(
            {
                "sid": sid,
                "upgrades": [],
                "pingInterval": _PING_INTERVAL_MS,
                "pingTimeout": _PING_TIMEOUT_MS,
            }
        )
    )

    # 2) Socket.IO v2 (EIO3): the SERVER initiates the CONNECT for the default namespace;
    # the client fires its 'connect' event on receipt and only then proceeds. (SIO v3+
    # flips this — client sends CONNECT first.) The device idles waiting on this, so send
    # it unprompted.
    connected_namespaces = {"/"}
    await ws.send_str("40")

    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                if msg.type in (
                    WSMsgType.CLOSE,
                    WSMsgType.CLOSING,
                    WSMsgType.CLOSED,
                ):
                    break
                if msg.type == WSMsgType.ERROR:
                    logger.warning("socket.io ws error sid=%s: %s", sid, ws.exception())
                    break
                continue

            data = msg.data
            eio_type = data[:1]
            if eio_type == "2":  # engineio PING -> reply PONG (keepalive)
                await ws.send_str("3" + data[1:])
            elif eio_type == "4":  # engineio MESSAGE -> socket.io packet
                # Answer a client-initiated namespace CONNECT so it fires 'connect' and
                # proceeds. App-level events (e.g. the device's 'ratta_ping' heartbeat)
                # need no server response — the channel merely staying connected is what
                # the device's app-data sync requires.
                await _maybe_reply_connect(ws, data[1:], connected_namespaces)
    finally:
        logger.debug("socket.io channel closed: sid=%s", sid)
    return ws


async def _maybe_reply_connect(
    ws: web.WebSocketResponse, sio_payload: str, connected_namespaces: set[str]
) -> None:
    """Echo a namespace CONNECT ("40[/nsp,]") when the client opens a new namespace.

    ``sio_payload`` is the socket.io packet (everything after the engineio '4'). Only a
    CONNECT (socket.io type '0') is acted on; everything else is ignored.
    """
    if sio_payload[:1] != "0":
        return
    rest = sio_payload[1:]
    namespace = "/"
    if rest.startswith("/"):
        comma = rest.find(",")
        namespace = rest if comma == -1 else rest[:comma]
    if namespace not in connected_namespaces:
        connected_namespaces.add(namespace)
        await ws.send_str("40" if namespace == "/" else f"40{namespace},")


def register(app: web.Application) -> None:
    """Register the realtime socket.io route on the main app.

    Wired BEFORE the ASGIResource catch-all is added in on_startup, so it wins the
    ``/socket.io/`` match.
    """
    app.router.add_get("/socket.io/", handle_socketio)
    app.router.add_get("/socket.io", handle_socketio)
