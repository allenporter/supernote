"""Authentication and HMAC-SHA256 signature verification for Socket.IO handshakes.

Provides `compute_handshake_signature` and `verify_handshake_signature`, which validate
`supernote.models.socket.SocketHandshakeParams` (`token`, `type`, `random`, `sign`)
sent by Supernote hardware tablets and `supernote.client.socket.SupernoteSocketClient`
when connecting to `supernote.server.socket`.
"""

import base64
import hashlib
import hmac
import logging
import re

from supernote.models.socket import SocketHandshakeParams

logger = logging.getLogger(__name__)

# Default pre-shared key used by Socket.IO client devices for protocol compatibility.
SOCKET_IO_KEY = "K+5xFzxbnB1iSZWqmu3Etw=="


def compute_handshake_signature(
    token: str,
    conn_type: str,
    random_val: str,
    secret_key: str = SOCKET_IO_KEY,
) -> str:
    """Compute HMAC-SHA256 signature for a Socket.IO handshake."""
    raw = f"{token}_{conn_type}_{random_val}"
    h = hmac.new(secret_key.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256)
    b64_sig = base64.b64encode(h.digest()).decode("utf-8")
    return re.sub(r"[^a-zA-Z0-9]", "", b64_sig)


def verify_handshake_signature(params: SocketHandshakeParams) -> bool:
    """Verify the signature parameter provided in a Socket.IO handshake."""
    if not params.sign:
        logger.warning("Missing signature in Socket.IO handshake")
        return False

    expected_sign = compute_handshake_signature(
        params.token, params.type, params.random
    )
    if hmac.compare_digest(params.sign, expected_sign):
        return True

    logger.warning("Handshake signature mismatch: received=%s", params.sign)
    return False
