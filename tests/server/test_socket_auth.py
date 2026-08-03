import base64
import hashlib
import hmac
import re

import jwt

from supernote.models.socket import SocketHandshakeParams
from supernote.server.services.user import JWT_ALGORITHM
from supernote.server.socket_auth import (
    SOCKET_IO_KEY,
    verify_handshake_signature,
    verify_handshake_token,
)


def test_verify_handshake_signature_valid() -> None:
    token = "test-token"
    conn_type = "file"
    random_val = "rnd123"
    raw = f"{token}_{conn_type}_{random_val}"
    h = hmac.new(SOCKET_IO_KEY.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256)
    b64_sig = base64.b64encode(h.digest()).decode("utf-8")
    sign = re.sub(r"[^a-zA-Z0-9]", "", b64_sig)

    params = SocketHandshakeParams(
        token=token,
        type=conn_type,
        random=random_val,
        sign=sign,
    )

    assert verify_handshake_signature(params) is True


def test_verify_handshake_signature_invalid() -> None:
    params = SocketHandshakeParams(
        token="test-token",
        type="file",
        random="rnd123",
        sign="wrong_signature",
    )

    assert verify_handshake_signature(params) is False


def test_verify_handshake_signature_missing_sign() -> None:
    params = SocketHandshakeParams(
        token="test-token",
        type="file",
        random="rnd123",
        sign="",
    )
    assert verify_handshake_signature(params) is False


def test_verify_handshake_token_valid() -> None:
    secret = "test-secret-key-32-characters-long!!"
    token = jwt.encode({"sub": "user@example.com"}, secret, algorithm=JWT_ALGORITHM)

    user_id = verify_handshake_token(token, secret)
    assert user_id == "user@example.com"


def test_verify_handshake_token_invalid() -> None:
    secret = "test-secret-key-32-characters-long!!"

    # Empty token string
    assert verify_handshake_token("", secret) is None

    # Invalid token string
    assert verify_handshake_token("invalid.jwt.token", secret) is None

    # Wrong secret key
    token = jwt.encode(
        {"sub": "user@example.com"}, "wrong-secret", algorithm=JWT_ALGORITHM
    )
    assert verify_handshake_token(token, secret) is None

    # Missing 'sub' claim in JWT payload
    no_sub_token = jwt.encode({"other": "claim"}, secret, algorithm=JWT_ALGORITHM)
    assert verify_handshake_token(no_sub_token, secret) is None
