"""Ambient execution provenance for domain event recording.

Carries actor identity and optional causal provenance (`cause_seq`, `reason`) across
async call chains via `ContextVar` so domain services stay decoupled from HTTP request
headers and event-log persistence details.
"""

import re
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from aiohttp import web

from supernote.server.exceptions import InvalidEventProvenance

CAUSE_SEQ_HEADER = "X-Supernote-Cause-Seq"
REASON_HEADER = "X-Supernote-Reason"
CLIENT_ACTOR_HEADER = "X-Supernote-Client"

MAX_ACTOR_LENGTH = 64
MAX_REASON_LENGTH = 512
MAX_INT64 = (1 << 63) - 1
_CLIENT_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._-]{1,56}$")


@dataclass(frozen=True)
class EventProvenance:
    """Immutable provenance metadata bound to the current async execution context."""

    actor: str | None = None
    cause_seq: int | None = None
    reason: str | None = None


_DEFAULT_PROVENANCE = EventProvenance()
_event_provenance_var: ContextVar[EventProvenance] = ContextVar(
    "supernote_event_provenance",
    default=_DEFAULT_PROVENANCE,
)


def get_event_provenance() -> EventProvenance:
    """Return the active `EventProvenance` for the current async execution context."""
    return _event_provenance_var.get()


@contextmanager
def bind_event_provenance(
    *,
    actor: str | None = None,
    cause_seq: int | None = None,
    reason: str | None = None,
    inherit: bool = True,
) -> Generator[EventProvenance]:
    """Bind provenance fields onto the current async context for the duration of a block.

    When `inherit=False` (used by autonomous system pipelines such as `ProcessorService`),
    any ambient caller `cause_seq`/`reason` on the stack is cleared rather than inherited.
    """
    base = _event_provenance_var.get() if inherit else _DEFAULT_PROVENANCE
    merged = EventProvenance(
        actor=actor if actor is not None else base.actor,
        cause_seq=cause_seq if cause_seq is not None else base.cause_seq,
        reason=reason if reason is not None else base.reason,
    )
    token = _event_provenance_var.set(merged)
    try:
        yield merged
    finally:
        _event_provenance_var.reset(token)


def format_actor_from_equipment(equipment_no: str | None) -> str | None:
    """Derive an actor label from a Supernote device serial number when non-web."""
    if not equipment_no:
        return None
    cleaned = equipment_no.strip()
    if not cleaned or cleaned.upper() == "WEB":
        return None
    return f"device:{cleaned}"[:MAX_ACTOR_LENGTH]


def resolve_request_provenance(
    request: web.Request,
    *,
    equipment_no: str | None = None,
) -> EventProvenance:
    """Extract and validate actor, `cause_seq`, and `reason` from an authenticated request."""
    cause_seq: int | None = None
    if raw_cause := request.headers.get(CAUSE_SEQ_HEADER, "").strip():
        try:
            parsed_cause = int(raw_cause)
        except ValueError as err:
            raise InvalidEventProvenance(
                f"Invalid {CAUSE_SEQ_HEADER}: expected positive 64-bit integer"
            ) from err
        if parsed_cause <= 0 or parsed_cause > MAX_INT64:
            raise InvalidEventProvenance(
                f"Invalid {CAUSE_SEQ_HEADER}: expected positive 64-bit integer"
            )
        cause_seq = parsed_cause

    reason: str | None = None
    if raw_reason := request.headers.get(REASON_HEADER, "").strip():
        if len(raw_reason) > MAX_REASON_LENGTH:
            raise InvalidEventProvenance(
                f"Invalid {REASON_HEADER}: exceeds maximum length of {MAX_REASON_LENGTH} characters"
            )
        reason = raw_reason

    if device_actor := format_actor_from_equipment(equipment_no):
        actor = device_actor
    elif raw_client := request.headers.get(CLIENT_ACTOR_HEADER, "").strip():
        if not _CLIENT_IDENTIFIER_RE.match(raw_client):
            raise InvalidEventProvenance(
                f"Invalid {CLIENT_ACTOR_HEADER}: must match [A-Za-z0-9._-]{{1,56}} (reserved actor namespaces are server-assigned)"
            )
        actor = f"client:{raw_client}"[:MAX_ACTOR_LENGTH]
    else:
        actor = "user:web"

    return EventProvenance(actor=actor, cause_seq=cause_seq, reason=reason)
