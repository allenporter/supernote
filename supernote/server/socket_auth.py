"""Authentication and signature verification helpers for Socket.IO connections."""

import base64
import hashlib
import hmac
import logging
import re

import jwt

from supernote.models.socket import SocketHandshakeParams
from supernote.server.services.user import JWT_ALGORITHM

logger = logging.getLogger(__name__)

# Default pre-shared key used by mobile client devices for protocol compatibility.
MOBILE_PROTOCOL_KEY = "K+5xFzxbnB1iSZWqmu3Etw=="


def verify_handshake_signature(params: SocketHandshakeParams, secret_key: str) -> bool:
    """Verify the signature parameter provided in a Socket.IO handshake."""
    if not params.sign:
        logger.warning("Missing signature in Socket.IO handshake")
        return False

    raw = f"{params.token}_{params.type}_{params.random}"

    h_mobile = hmac.new(
        MOBILE_PROTOCOL_KEY.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256
    )
    b64_mobile = base64.b64encode(h_mobile.digest()).decode("utf-8")
    if params.sign == re.sub(r"[^a-zA-Z0-9]", "", b64_mobile):
        return True

    # Server secret_key HMAC-SHA256 (hexdigest and base64)
    h_secret = hmac.new(secret_key.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256)
    if params.sign == h_secret.hexdigest():
        return True

    b64_secret = base64.b64encode(h_secret.digest()).decode("utf-8")
    if params.sign == re.sub(r"[^a-zA-Z0-9]", "", b64_secret):
        return True

    # Fallback: MD5 hash comparison
    if params.sign == hashlib.md5(raw.encode("utf-8")).hexdigest():
        return True

    logger.warning("Handshake signature mismatch: received=%s", params.sign)
    return False


def verify_handshake_token(token: str, secret_key: str) -> str | None:
    """Verify JWT token provided during Socket.IO handshake and extract user ID.

    Args:
        token: JWT string.
        secret_key: Server secret key used for signing JWTs.

    Returns:
        The authenticated user ID (email/username), or None if invalid or expired.
    """
    if not token:
        logger.warning("Empty token in Socket.IO handshake")
        return None

    try:
        payload = jwt.decode(token, secret_key, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            logger.warning("JWT payload missing 'sub' claim")
            return None
        return str(user_id)
    except jwt.PyJWTError as err:
        logger.warning("Failed to decode JWT in Socket.IO handshake: %s", err)
        return None
