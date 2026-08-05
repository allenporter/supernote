"""Tests for outbound webhook payload models."""

from supernote.models.webhook import NoteSyncCompletedPayload, WebhookFileVO


def test_note_sync_completed_payload_serializes_to_dict() -> None:
    payload = NoteSyncCompletedPayload(
        event="note.sync_completed",
        timestamp=1730000000,
        file=WebhookFileVO(id=42, path="Note/Daily/2026-08-04.note"),
    )

    assert payload.to_dict() == {
        "event": "note.sync_completed",
        "timestamp": 1730000000,
        "file": {"id": 42, "path": "Note/Daily/2026-08-04.note"},
    }


def test_note_sync_completed_payload_excludes_user_id() -> None:
    """The payload has no field for the internal, per-user database ID."""
    payload = NoteSyncCompletedPayload(
        event="note.sync_completed",
        timestamp=1730000000,
        file=WebhookFileVO(id=1, path="a.note"),
    )

    assert "user_id" not in payload.to_dict()
    assert not hasattr(payload, "user_id")
