"""THROWAWAY socket.io capture prototype (wayfinder zero-banner-sync, ticket 01).

The Supernote device opens a realtime channel with:

    GET /socket.io/?sign=..&random=..&EIO=3&transport=websocket&type=<deviceId>&token=<jwt>

i.e. **Engine.IO protocol v3 / Socket.IO protocol v2**, going straight to
``transport=websocket`` (no polling-first upgrade dance). The production server has
no realtime server, so this websocket falls through to the MCP/auth ``ASGIResource``
catch-all whose aiohttp_asgi bridge raises on the websocket-close ASGI message -> 500.

This module hand-rolls just enough EIO3/SIO2 to make the device **connect cleanly**
and then **logs every frame it sends**, so we can observe the event surface (namespaces,
event names, payloads) that defines destination bar B. It is dependency-free on purpose:

* modern ``python-socketio`` / ``python-engineio`` (v5 / v4) **hard-reject EIO=3** with a
  400 "unsupported version" and have removed the EIO3 encoding paths, so the library route
  would need an old (<5 / <4) pin. Hand-rolling over aiohttp's native ``WebSocketResponse``
  avoids any dependency and survives ``uv run`` (no lockfile change), and is transparent
  for capture.

Wire-format cheat-sheet (text frames over the single websocket):

    packet = <engineio_type><payload>
    engineio types : 0 open  1 close  2 ping  3 pong  4 message  5 upgrade  6 noop
    a Socket.IO packet rides inside an engineio MESSAGE(4):
        socketio types : 0 CONNECT 1 DISCONNECT 2 EVENT 3 ACK 4 ERROR 5 BIN_EVENT 6 BIN_ACK
    so on the wire:
        "0{...}"                 engineio OPEN   (handshake, server -> client)
        "40" / "40/nsp,"         MESSAGE+CONNECT (namespace connect)
        "42[\"name\",payload]"   MESSAGE+EVENT
        "43<ackid>[...]"         MESSAGE+ACK
        "2" / "3"                engineio ping / pong  (EIO3: CLIENT pings, server pongs)

Enable by launching the server with ``SUPERNOTE_SOCKETIO_CAPTURE=1``. Off by default;
touches nothing when unset. Delete this file + its two call-sites in app.py to revert.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from .routes.decorators import public_route

logger = logging.getLogger("supernote.socketio_capture")

# EIO3 handshake defaults the client is happy with.
_PING_INTERVAL_MS = 25000
_PING_TIMEOUT_MS = 60000


def _capture_log_path(request: web.Request) -> Path:
    """Dedicated capture log next to trace.log so the driver can just tail it."""
    config = request.app["config"]
    root = Path(config.storage_root) / "system"
    root.mkdir(parents=True, exist_ok=True)
    return root / "socketio-capture.log"


def _record(request: web.Request, kind: str, **fields: Any) -> None:
    """Append one structured line to the capture log AND the app logger."""
    entry = {"ts": time.time(), "kind": kind, **fields}
    line = json.dumps(entry, ensure_ascii=False)
    try:
        with _capture_log_path(request).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # pragma: no cover - logging must never break capture
        logger.exception("failed writing capture log")
    logger.info("[socketio-capture] %s", line)


def _decode_sio(payload: str) -> dict[str, Any]:
    """Best-effort decode of an engineio-MESSAGE (type '4') socket.io packet body.

    payload is everything after the leading '4', e.g. '2/nsp,7["evt",{...}]'.
    Returns the parsed pieces we care about for capture (never raises).
    """
    out: dict[str, Any] = {"raw": payload}
    if not payload:
        return out
    sio_type = payload[0]
    out["sio_type"] = sio_type
    rest = payload[1:]
    # optional namespace: "/foo,..." up to the first comma before the json/ackid
    namespace = "/"
    if rest.startswith("/"):
        comma = rest.find(",")
        if comma != -1:
            namespace = rest[:comma]
            rest = rest[comma + 1 :]
    out["namespace"] = namespace
    # optional numeric ack id preceding the json array
    ack = ""
    while rest[:1].isdigit():
        ack += rest[0]
        rest = rest[1:]
    if ack:
        out["ack_id"] = ack
    if rest:
        try:
            data = json.loads(rest)
            out["data"] = data
            if sio_type == "2" and isinstance(data, list) and data:
                out["event"] = data[0]
                out["args"] = data[1:]
        except json.JSONDecodeError:
            out["data_raw"] = rest
    return out


@public_route  # bypass jwt_auth_middleware; device carries its token as a query param
async def handle_socketio(request: web.Request) -> web.StreamResponse:
    q = request.query
    if request.headers.get("Upgrade", "").lower() != "websocket":
        # Device only ever uses transport=websocket; nothing else to serve.
        return web.json_response({"error": "websocket transport required"}, status=400)

    token = q.get("token")
    device = q.get("type")
    # Permissive auth: verify for the record but accept regardless so capture always
    # happens even if the device's auth handshake differs from the REST one.
    verified = None
    if token:
        try:
            session = await request.app["user_service"].verify_token(token)
            verified = bool(session)
        except Exception:
            verified = False

    _record(
        request,
        "connect",
        device=device,
        eio=q.get("EIO"),
        transport=q.get("transport"),
        sign=q.get("sign"),
        random=q.get("random"),
        token_present=token is not None,
        token_verified=verified,
        query={k: v for k, v in q.items() if k != "token"},
    )

    ws = web.WebSocketResponse(protocols=("websocket",), heartbeat=None)
    await ws.prepare(request)

    sid = secrets.token_hex(12)
    # 1) Engine.IO OPEN frame.
    open_pkt = "0" + json.dumps(
        {
            "sid": sid,
            "upgrades": [],
            "pingInterval": _PING_INTERVAL_MS,
            "pingTimeout": _PING_TIMEOUT_MS,
        }
    )
    await ws.send_str(open_pkt)
    _record(request, "sent", sid=sid, frame=open_pkt)

    # Socket.IO v2 (EIO3): the SERVER initiates the CONNECT for the default
    # namespace; the client fires its 'connect' event on receipt and only then
    # emits/subscribes. (SIO v3+ flips this — client sends CONNECT first.) Live
    # capture showed the device opening the transport and idling with pings but
    # never sending a client '40', so it's waiting on the server. Send it.
    connected_namespaces = {"/"}
    await ws.send_str("40")
    _record(
        request, "sent", sid=sid, frame="40", note="server-initiated CONNECT (SIO v2)"
    )

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                data = msg.data
                eio_type = data[:1]
                if eio_type == "2":  # engineio PING -> reply PONG
                    pong = "3" + data[1:]
                    await ws.send_str(pong)
                    _record(request, "ping", sid=sid, recv=data, sent=pong)
                    continue
                if eio_type == "4":  # engineio MESSAGE -> socket.io packet
                    decoded = _decode_sio(data[1:])
                    _record(request, "message", sid=sid, **decoded)
                    # Answer a namespace CONNECT so the client fires its 'connect'
                    # event and proceeds; echo the client's namespace verbatim.
                    if decoded.get("sio_type") == "0":
                        ns = decoded.get("namespace", "/")
                        if ns not in connected_namespaces:
                            connected_namespaces.add(ns)
                            reply = "40" if ns == "/" else f"40{ns},"
                            await ws.send_str(reply)
                            _record(request, "sent", sid=sid, frame=reply)
                    # NOTE (live RE): the device emits an app-level 'ratta_ping'
                    # heartbeat (~every 54s) and holds "App Data Sync Failed" open.
                    # Connecting + heartbeat is NOT sufficient to clear that banner,
                    # and a naive '42["ratta_pong"]' reply did not clear it either.
                    # What the device needs over this channel is the subject of the
                    # graduated realtime-app-data implementation ticket; the capture
                    # prototype intentionally stays observe-only + stable here.
                    continue
                # open/close/upgrade/noop or anything else: just record it raw.
                _record(request, "frame", sid=sid, eio_type=eio_type, raw=data)
            elif msg.type == WSMsgType.BINARY:
                _record(request, "binary", sid=sid, nbytes=len(msg.data))
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
                break
            elif msg.type == WSMsgType.ERROR:
                _record(request, "ws_error", sid=sid, exc=str(ws.exception()))
                break
    finally:
        _record(request, "disconnect", sid=sid)
    return ws


def maybe_register(app: web.Application) -> bool:
    """Register the capture route when SUPERNOTE_SOCKETIO_CAPTURE is truthy.

    Registered on the main app (port 8080) BEFORE the ASGIResource catch-all is
    added in on_startup, so it wins the /socket.io/ match. Returns True if wired.
    """
    import os

    if not os.environ.get("SUPERNOTE_SOCKETIO_CAPTURE"):
        return False
    app.router.add_get("/socket.io/", handle_socketio)
    app.router.add_get("/socket.io", handle_socketio)
    logger.warning(
        "socket.io CAPTURE prototype enabled at /socket.io/ (EIO3/SIO2 hand-roll)"
    )
    return True
