"""Pure data types and opaque cursor codec for the `events` component.

This module defines the transport-free, database-free internal API models used
by `supernote.server.components.events.service.EventLogService` and its
consumers (HTTP routes, MCP tools, and downstream server components):

- `EventFeedPage`: Paginated slice of per-user `DomainEventRecorded` records
  returned by `EventLogService.list_events`.
- `encode_sync_token` / `decode_sync_token`: Canonical URL-safe `v1:<seq>`
  cursor codec used to checkpoint incremental event log syncs.
- Default retention and pagination constants (`DEFAULT_EVENT_LOG_RETENTION_DAYS`,
  `DEFAULT_FEED_LIMIT`, `MAX_FEED_LIMIT`).

Because this module has zero SQLAlchemy, `aiohttp`, or component-service
imports, other components and platform modules can import these types without
introducing heavy runtime coupling.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from supernote.server.events import DomainEventRecorded
from supernote.server.exceptions import InvalidInputError

__all__ = [
    "EventFeedPage",
]

DEFAULT_EVENT_LOG_RETENTION_DAYS = 90
"""Default number of days to retain persisted domain events before pruning."""

DEFAULT_FEED_LIMIT = 200
"""Default maximum number of events returned per `list_events` page."""

MAX_FEED_LIMIT = 1000
"""Hard upper bound on the `limit` parameter accepted by `list_events`."""


@dataclass(slots=True)
class EventFeedPage:
    """Paginated response for per-user domain event feed queries.

    Returned by `EventLogService.list_events` and translated into wire DTOs
    (such as `supernote.models.events.EventFeedListVO`) by transport platforms.
    """

    events: list[DomainEventRecorded]
    """Ordered list of matching `DomainEventRecorded` entries in ascending `seq` order."""

    next_sync_token: str | None
    """Opaque checkpoint token for the next poll, or `None` if no events exist yet.

    When `events` is empty due to filters (`event_types`, `file_id`, or
    `exclude_actors`), this still advances to the user's latest sequence number
    so callers do not repeatedly re-scan filtered history.
    """

    has_more: bool
    """`True` when more matching events exist beyond `limit`."""


def encode_sync_token(seq: int) -> str:
    """Encode an internal monotonic sequence number into an opaque sync token.

    Tokens use unpadded URL-safe Base64 over the canonical ASCII payload
    ``v1:<seq>``. Callers should treat tokens as opaque strings; the version
    prefix allows future cursor format evolution without breaking clients.

    Args:
        seq: Strictly positive monotonic event sequence number (`UserEventDO.seq`).

    Returns:
        URL-safe, unpadded Base64 sync token string.

    Raises:
        ValueError: If `seq` is not a positive integer.
    """
    if seq <= 0:
        raise ValueError(f"Sequence number must be positive, got {seq}")
    raw = f"v1:{seq}".encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_sync_token(token: str) -> int:
    """Decode and strictly validate an opaque sync token back into a sequence number.

    Rejects non-canonical padding, non-ASCII encodings, unknown version
    prefixes, zero/negative sequence values, and malformed Base64 payloads so
    invalid client cursors fail fast with HTTP 400 (`InvalidInputError`).

    Args:
        token: Opaque sync token previously returned by `encode_sync_token` or
            `EventFeedPage.next_sync_token`.

    Returns:
        The decoded positive integer sequence number.

    Raises:
        InvalidInputError: If `token` is malformed or non-canonical.
    """
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii")
    except (ValueError, UnicodeDecodeError) as err:
        raise InvalidInputError(f"Invalid sync_token: {token!r}") from err
    prefix, sep, raw_seq = decoded.partition(":")
    if prefix != "v1" or sep != ":" or not (raw_seq.isascii() and raw_seq.isdigit()):
        raise InvalidInputError(f"Invalid sync_token: {token!r}")
    seq = int(raw_seq)
    if seq <= 0 or encode_sync_token(seq) != token:
        raise InvalidInputError(f"Invalid sync_token: {token!r}")
    return seq
