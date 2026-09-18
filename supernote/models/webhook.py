"""Data models for outbound webhook payloads.

See :mod:`supernote.server.services.webhook` for the dispatcher that builds
and signs these payloads before sending them to configured endpoints.
"""

from dataclasses import dataclass

from mashumaro.mixins.json import DataClassJSONMixin


@dataclass
class WebhookFileVO(DataClassJSONMixin):
    """File metadata included in a `note.sync_completed` webhook payload."""

    id: int
    """The internal ID of the synced file."""

    path: str
    """The full path of the file, relative to the user's root directory."""


@dataclass
class NoteSyncCompletedPayload(DataClassJSONMixin):
    """Payload sent for the `note.sync_completed` outbound webhook event.

    Corresponds to `EVENT_NOTE_SYNC_COMPLETED` in
    `supernote.server.services.webhook`.

    Intentionally excludes the internal `user_id` (a private, per-user
    database identifier) -- see that module for discussion.
    """

    event: str
    """The webhook event name. Always `note.sync_completed` today."""

    timestamp: int
    """Unix timestamp (seconds) of when the event was dispatched."""

    file: WebhookFileVO
    """Metadata about the file that finished syncing."""
