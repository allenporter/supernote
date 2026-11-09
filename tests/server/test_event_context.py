"""Unit tests for ambient event provenance context and request header parsing."""

import pytest
from aiohttp.test_utils import make_mocked_request

from supernote.server.event_context import (
    CAUSE_SEQ_HEADER,
    CLIENT_ACTOR_HEADER,
    REASON_HEADER,
    EventProvenance,
    bind_event_provenance,
    format_actor_from_equipment,
    get_event_provenance,
    resolve_request_provenance,
)
from supernote.server.exceptions import InvalidEventProvenance


def test_bind_event_provenance_nesting_and_reset() -> None:
    """Verify nested bind_event_provenance scopes merge and restore cleanly."""
    assert get_event_provenance() == EventProvenance()

    with bind_event_provenance(actor="client:todo-agent", cause_seq=55) as outer:
        assert outer == EventProvenance(
            actor="client:todo-agent", cause_seq=55, reason=None
        )
        assert get_event_provenance() == outer

        with bind_event_provenance(reason="Matched crossed-out task") as inner:
            assert inner == EventProvenance(
                actor="client:todo-agent",
                cause_seq=55,
                reason="Matched crossed-out task",
            )
            assert get_event_provenance() == inner

        assert get_event_provenance() == outer

    assert get_event_provenance() == EventProvenance()


def test_bind_event_provenance_inherit_false_clears_ambient_caller_context() -> None:
    """Verify system workers binding inherit=False do not leak ambient HTTP caller provenance."""
    with bind_event_provenance(
        actor="client:web-caller", cause_seq=999, reason="User clicked button"
    ):
        with bind_event_provenance(
            actor="system:processor", inherit=False
        ) as system_ctx:
            assert system_ctx == EventProvenance(
                actor="system:processor", cause_seq=None, reason=None
            )
            assert get_event_provenance() == system_ctx

        assert get_event_provenance() == EventProvenance(
            actor="client:web-caller", cause_seq=999, reason="User clicked button"
        )


def test_format_actor_from_equipment() -> None:
    """Verify device serial numbers produce device:<sn> while WEB/empty return None."""
    assert format_actor_from_equipment(None) is None
    assert format_actor_from_equipment("") is None
    assert format_actor_from_equipment("   ") is None
    assert format_actor_from_equipment("WEB") is None
    assert format_actor_from_equipment("web") is None
    assert format_actor_from_equipment("SN1000234") == "device:SN1000234"


def test_resolve_request_provenance_precedence_and_headers() -> None:
    """Verify actor precedence (device > client header > user:web) and provenance headers."""
    web_req = make_mocked_request("POST", "/api/file/schedule/task")
    assert resolve_request_provenance(web_req, equipment_no="WEB") == EventProvenance(
        actor="user:web",
        cause_seq=None,
        reason=None,
    )

    dev_req = make_mocked_request(
        "POST",
        "/api/file/schedule/task",
        headers={CLIENT_ACTOR_HEADER: "ignored-when-device-session"},
    )
    assert resolve_request_provenance(
        dev_req, equipment_no="SN998877"
    ) == EventProvenance(
        actor="device:SN998877",
        cause_seq=None,
        reason=None,
    )

    agent_req = make_mocked_request(
        "PUT",
        "/api/file/schedule/task/123",
        headers={
            CLIENT_ACTOR_HEADER: "magic-todo-agent",
            CAUSE_SEQ_HEADER: "772252421643567298",
            REASON_HEADER: "Task checked off on page P1",
        },
    )
    assert resolve_request_provenance(agent_req, equipment_no="WEB") == EventProvenance(
        actor="client:magic-todo-agent",
        cause_seq=772252421643567298,
        reason="Task checked off on page P1",
    )


@pytest.mark.parametrize(
    "headers",
    [
        {CAUSE_SEQ_HEADER: "not-an-int"},
        {CAUSE_SEQ_HEADER: "0"},
        {CAUSE_SEQ_HEADER: "-12"},
        {CAUSE_SEQ_HEADER: str(10**30)},
        {REASON_HEADER: "x" * 513},
        {CLIENT_ACTOR_HEADER: "bad actor spaces!"},
        {CLIENT_ACTOR_HEADER: "api_key:spoofed"},
        {CLIENT_ACTOR_HEADER: "mcp:claude-code"},
        {CLIENT_ACTOR_HEADER: "system:processor"},
        {CLIENT_ACTOR_HEADER: "device:SN123"},
        {CLIENT_ACTOR_HEADER: "user:web"},
        {CLIENT_ACTOR_HEADER: "client:double-prefix"},
    ],
)
def test_resolve_request_provenance_rejects_invalid_headers(
    headers: dict[str, str],
) -> None:
    """Verify malformed or spoofed provenance headers raise InvalidEventProvenance (400)."""
    req = make_mocked_request("POST", "/api/file/schedule/task", headers=headers)
    with pytest.raises(InvalidEventProvenance):
        resolve_request_provenance(req)
