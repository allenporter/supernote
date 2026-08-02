"""Authentication and signature verification helpers for Socket.IO connections."""

import hashlib
import hmac
import logging

import jwt

from supernote.models.socket import SocketHandshakeParams
from supernote.server.services.user import JWT_ALGORITHM

logger = logging.getLogger(__name__)


def verify_handshake_signature(params: SocketHandshakeParams, secret_key: str) -> bool:
    """Verify the signature parameter provided in a Socket.IO handshake.

    Formula evaluated: MD5(token + '_' + type + '_' + random)

    Args:
        params: Handshake parameters received from the client query string.
        secret_key: Server authentication secret key.

    Returns:
        True if the signature is valid or omitted for dev testing, False otherwise.
    """
    if not params.sign:
        # If signature is not provided, allow connection in lenient dev mode
        return True

    raw = f"{params.token}_{params.type}_{params.random}"
    expected_sign = hashlib.md5(raw.encode("utf-8")).hexdigest()

    if params.sign == expected_sign:
        return True

    # Also check HMAC with secret_key as alternative valid signature format
    expected_hmac = hmac.new(
        secret_key.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if params.sign == expected_hmac:
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
