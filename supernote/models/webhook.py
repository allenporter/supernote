"""Data models and event constants for outbound HMAC-signed webhook payloads.

This module defines `WebhookPayload`, `WebhookFileVO`, and event type constants
(`EVENT_NOTE_SYNC_COMPLETED`, `EVENT_NOTE_PROCESSING_COMPLETED`) dispatched when a `.note` file
finishes syncing or completes background OCR/AI processing. See `supernote.models` and
`supernote.guides.webhooks_and_integrations` for payload schemas and signature verification.
"""

from dataclasses import dataclass

from mashumaro.mixins.json import DataClassJSONMixin

EVENT_NOTE_SYNC_COMPLETED = "note.sync_completed"
EVENT_NOTE_PROCESSING_COMPLETED = "note.processing_completed"


@dataclass
class WebhookFileVO(DataClassJSONMixin):
    """File metadata included in outbound note webhook payloads."""

    id: int
    """The internal ID of the synced file."""

    name: str
    """The filename of the note (e.g. `2026-08-04.note`)."""

    path: str
    """The full path of the file, relative to the user's root directory."""


@dataclass
class WebhookPayload(DataClassJSONMixin):
    """Base payload for outbound webhook events."""

    event: str
    """The webhook event name (e.g. `note.sync_completed`)."""

    timestamp: int
    """Unix timestamp (seconds) of when the event was dispatched."""


@dataclass
class NoteSyncCompletedPayload(WebhookPayload):
    """Payload sent for the `note.sync_completed` outbound webhook event.

    Corresponds to `EVENT_NOTE_SYNC_COMPLETED` in
    `supernote.server.services.webhook`.

    Intentionally excludes the internal `user_id` (a private, per-user
    database identifier) -- see that module for discussion.
    """

    file: WebhookFileVO
    """Metadata about the file that finished syncing."""


@dataclass
class NoteProcessingCompletedPayload(WebhookPayload):
    """Payload sent for the `note.processing_completed` outbound webhook event.

    Corresponds to `EVENT_NOTE_PROCESSING_COMPLETED` in
    `supernote.server.services.webhook`.
    """

    file: WebhookFileVO
    """Metadata about the file that finished processing."""
