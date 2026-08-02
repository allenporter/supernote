"""Tests for Socket.IO handshake authentication functions."""

import hashlib
import hmac

import jwt

from supernote.models.socket import SocketHandshakeParams
from supernote.server.services.user import JWT_ALGORITHM
from supernote.server.socket_auth import (
    verify_handshake_signature,
    verify_handshake_token,
)


def test_verify_handshake_signature_valid() -> None:
    token = "test-token"
    conn_type = "file"
    random_val = "rnd123"
    raw = f"{token}_{conn_type}_{random_val}"
    sign = hashlib.md5(raw.encode("utf-8")).hexdigest()

    params = SocketHandshakeParams(
        token=token,
        type=conn_type,
        random=random_val,
        sign=sign,
    )

    assert verify_handshake_signature(params, "secret") is True


def test_verify_handshake_signature_hmac_valid() -> None:
    token = "test-token"
    conn_type = "file"
    random_val = "rnd123"
    secret_key = "my-secret-key"
    raw = f"{token}_{conn_type}_{random_val}"
    sign = hmac.new(
        secret_key.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    params = SocketHandshakeParams(
        token=token,
        type=conn_type,
        random=random_val,
        sign=sign,
    )

    assert verify_handshake_signature(params, secret_key) is True


def test_verify_handshake_signature_invalid() -> None:
    params = SocketHandshakeParams(
        token="test-token",
        type="file",
        random="rnd123",
        sign="wrong_signature",
    )

    assert verify_handshake_signature(params, "secret") is False


def test_verify_handshake_signature_missing_sign() -> None:
    params = SocketHandshakeParams(
        token="test-token",
        type="file",
        random="rnd123",
        sign="",
    )
    assert verify_handshake_signature(params, "secret") is True


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
