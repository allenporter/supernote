"""Unit tests for `supernote.server.components.events.models`."""

from __future__ import annotations

import base64

import pytest

from supernote.server.components.events.models import (
    decode_sync_token,
    encode_sync_token,
)
from supernote.server.exceptions import InvalidInputError


@pytest.mark.parametrize("seq", [1, 42, 999_999])
def test_sync_token_round_trip(seq: int) -> None:
    """Verify encode_sync_token / decode_sync_token round-trips positive integers."""
    token = encode_sync_token(seq)
    assert isinstance(token, str)
    assert "=" not in token
    assert decode_sync_token(token) == seq


@pytest.mark.parametrize("bad_seq", [0, -1, -100])
def test_encode_sync_token_rejects_non_positive(bad_seq: int) -> None:
    """Verify encode_sync_token rejects zero and negative sequence numbers."""
    with pytest.raises(ValueError, match="positive"):
        encode_sync_token(bad_seq)


@pytest.mark.parametrize(
    "bad_token",
    [
        "",
        "100",
        "not-valid-base64!!!",
        base64.urlsafe_b64encode(b"v2:1").decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(b"v1:0").decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(b"v1:-5").decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(b"v1:abc").decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(b"v1:01").decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(b"v1:1").decode("ascii"),  # non-canonical padding
    ],
)
def test_decode_sync_token_rejects_invalid_tokens(bad_token: str) -> None:
    """Verify decode_sync_token rejects malformed or non-canonical tokens."""
    with pytest.raises(InvalidInputError):
        decode_sync_token(bad_token)
