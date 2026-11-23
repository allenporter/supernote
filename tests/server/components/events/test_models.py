"""Unit tests for `supernote.server.components.events.models`."""

from __future__ import annotations

import base64

import pytest

from supernote.server.components.events.models import (
    DEFAULT_EVENT_LOG_RETENTION_DAYS,
    DEFAULT_FEED_LIMIT,
    MAX_FEED_LIMIT,
    EventFeedPage,
    decode_sync_token,
    encode_sync_token,
)
from supernote.server.events import DomainEventRecorded
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


def test_event_feed_page_and_constants() -> None:
    """Verify EventFeedPage dataclass fields and feed defaults."""
    event = DomainEventRecorded(
        user_id=1,
        seq=5,
        timestamp_ms=1_700_000_000_000,
        event_type="vfs.created",
        actor="user:web",
        entity_type="file",
        entity_id="42",
        related_file_id=42,
        payload={"path": "/NOTE/a.note"},
    )
    page = EventFeedPage(
        events=[event],
        next_sync_token=encode_sync_token(5),
        has_more=False,
    )
    assert page.events == [event]
    assert page.next_sync_token == encode_sync_token(5)
    assert page.has_more is False
    assert DEFAULT_EVENT_LOG_RETENTION_DAYS == 90
    assert 1 <= DEFAULT_FEED_LIMIT <= MAX_FEED_LIMIT
