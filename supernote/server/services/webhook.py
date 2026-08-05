"""Outbound webhook dispatch for server events.

Listens on the internal :class:`~supernote.server.events.LocalEventBus` and,
for every configured endpoint subscribed to a given event name, sends a
signed HTTP POST notification. Delivery is best-effort: a slow or failing
endpoint is logged and skipped, it never raises back into the caller and
never blocks or delays the operation that triggered the event (e.g. a
device sync request).
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import aiohttp

from ..config import WebhookConfig, WebhookEndpointConfig
from ..events import Event, LocalEventBus, NoteUpdatedEvent

logger = logging.getLogger(__name__)

# Name of the event dispatched when a .note file finishes syncing to the
# server. Fired from the same point the processing pipeline is enqueued
# (see NoteUpdatedEvent), i.e. as soon as the device's upload completes.
EVENT_NOTE_SYNC_COMPLETED = "note.sync_completed"

SIGNATURE_HEADER = "X-Supernote-Signature"
EVENT_HEADER = "X-Supernote-Event"

REQUEST_TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.0


def sign_payload(secret: str, body: bytes) -> str:
    """Compute the `sha256=<hex>` HMAC signature for a webhook payload body."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    """Verify a `sha256=<hex>` signature against `body` using constant-time comparison."""
    expected = sign_payload(secret, body)
    return hmac.compare_digest(expected, signature)


class WebhookService:
    """Dispatches signed outbound webhook notifications for subscribed events."""

    def __init__(self, config: WebhookConfig, event_bus: LocalEventBus) -> None:
        self.config = config
        self.event_bus = event_bus

    def start(self) -> None:
        """Subscribe to the events that can trigger webhook dispatch."""
        if not self.config.enabled or not self.config.endpoints:
            logger.debug("Webhook dispatch disabled or no endpoints configured.")
            return
        self.event_bus.subscribe(NoteUpdatedEvent, self._handle_note_updated)
        logger.info(
            f"WebhookService started with {len(self.config.endpoints)} endpoint(s)."
        )

    async def _handle_note_updated(self, event: Event) -> None:
        """Translate a NoteUpdatedEvent into a note.sync_completed webhook."""
        if not isinstance(event, NoteUpdatedEvent):
            return
        payload = {
            "event": EVENT_NOTE_SYNC_COMPLETED,
            "timestamp": int(time.time()),
            "user_id": event.user_id,
            "file": {
                "id": event.file_id,
                "path": event.file_path,
            },
        }
        await self.dispatch(EVENT_NOTE_SYNC_COMPLETED, payload)

    async def dispatch(self, event_name: str, payload: dict[str, Any]) -> None:
        """Send `payload` to every configured endpoint subscribed to `event_name`.

        Never raises. Endpoints are notified concurrently and independently;
        one endpoint failing has no effect on delivery to the others.
        """
        endpoints = [ep for ep in self.config.endpoints if event_name in ep.events]
        if not endpoints:
            return
        await asyncio.gather(
            *(self._send(endpoint, event_name, payload) for endpoint in endpoints)
        )

    async def _send(
        self,
        endpoint: WebhookEndpointConfig,
        event_name: str,
        payload: dict[str, Any],
    ) -> None:
        """POST `payload` to a single endpoint, retrying transient failures.

        Client errors (4xx) are not retried. Network errors, timeouts, and
        server errors (5xx) are retried up to MAX_ATTEMPTS with a linear
        backoff. All failures are logged (without the secret or signature)
        and swallowed.
        """
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", EVENT_HEADER: event_name}
        if endpoint.secret:
            headers[SIGNATURE_HEADER] = sign_payload(endpoint.secret, body)

        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        endpoint.url, data=body, headers=headers
                    ) as response:
                        if response.status < 400:
                            return
                        if response.status < 500:
                            logger.warning(
                                f"Webhook {event_name} to {endpoint.url} rejected "
                                f"with status {response.status}; not retrying."
                            )
                            return
                        logger.warning(
                            f"Webhook {event_name} to {endpoint.url} failed with "
                            f"status {response.status} (attempt {attempt}/{MAX_ATTEMPTS})."
                        )
            except (aiohttp.ClientError, TimeoutError) as e:
                logger.warning(
                    f"Webhook {event_name} to {endpoint.url} failed: "
                    f"{type(e).__name__} (attempt {attempt}/{MAX_ATTEMPTS})."
                )

            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)

        logger.error(
            f"Webhook {event_name} to {endpoint.url} failed after "
            f"{MAX_ATTEMPTS} attempts; giving up."
        )
