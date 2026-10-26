"""Outbound webhook dispatch for server events.

Listens on the internal `supernote.server.events.LocalEventBus` and,
for every configured endpoint subscribed to a given event name (`note.sync_completed`,
`note.processing_completed`), sends an HMAC-SHA256 signed HTTP `POST` notification
(`X-Supernote-Signature`, `X-Supernote-Event`) with payload models from
`supernote.models.webhook`. Delivery is best-effort with bounded concurrency and retry
backoff: a slow or failing endpoint is logged and skipped, never blocking device sync.
See `supernote.guides.webhooks_and_integrations` and `supernote.guides.configuration`.
"""

import asyncio
import hashlib
import hmac
import logging
import time
from pathlib import PurePosixPath

import aiohttp
from yarl import URL

from supernote.models.webhook import (
    EVENT_NOTE_PROCESSING_COMPLETED,
    EVENT_NOTE_SYNC_COMPLETED,
    NoteProcessingCompletedPayload,
    NoteSyncCompletedPayload,
    WebhookFileVO,
    WebhookPayload,
)

from ..config import WebhookConfig, WebhookEndpointConfig
from ..events import (
    Event,
    LocalEventBus,
    NoteProcessingCompletedEvent,
    NoteUpdatedEvent,
)
from .user import UserService

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-Supernote-Signature"
EVENT_HEADER = "X-Supernote-Event"

REQUEST_TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.0
MAX_CONCURRENT_REQUESTS = 5


def sign_payload(secret: str, body: bytes) -> str:
    """Compute the `sha256=<hex>` HMAC signature for a webhook payload body."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(secret: str, body: bytes, signature_header: str) -> bool:
    """Verify a webhook payload body against an `X-Supernote-Signature` header.

    Uses constant-time comparison via :func:`hmac.compare_digest` to prevent
    timing side-channel attacks.
    """
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = sign_payload(secret, body)
    return hmac.compare_digest(expected, signature_header)


def _redact_url(raw_url: str) -> str:
    """Strip credentials, query parameters, and fragments from a URL before logging."""
    try:
        parsed = URL(raw_url)
        if not parsed.scheme or not parsed.host:
            return "<invalid-url>"
        return str(
            parsed.with_user(None)
            .with_password(None)
            .with_query(None)
            .with_fragment(None)
        )
    except ValueError:
        return "<invalid-url>"


class WebhookService:
    """Dispatches signed outbound webhook notifications for subscribed events."""

    def __init__(
        self,
        config: WebhookConfig,
        event_bus: LocalEventBus,
        user_service: UserService,
        max_concurrency: int = MAX_CONCURRENT_REQUESTS,
    ) -> None:
        self.config = config
        self.event_bus = event_bus
        self.user_service = user_service
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._session: aiohttp.ClientSession | None = None
        self._endpoints_by_user: dict[int, list[WebhookEndpointConfig]] = {}

    async def start(self) -> None:
        """Resolve endpoint users and subscribe to the events that can trigger webhook dispatch."""
        if not self.config.enabled or not self.config.endpoints:
            logger.debug("Webhook dispatch disabled or no endpoints configured.")
            return
        self._endpoints_by_user = {}
        for endpoint in self.config.endpoints:
            user = await self.user_service.get_user_by_email(endpoint.user)
            if user is None:
                logger.warning(
                    f"Webhook endpoint user {endpoint.user!r} not found; skipping endpoint."
                )
                continue
            self._endpoints_by_user.setdefault(user.id, []).append(endpoint)
        self._session = aiohttp.ClientSession()
        self.event_bus.subscribe(NoteUpdatedEvent, self._handle_note_updated)
        self.event_bus.subscribe(
            NoteProcessingCompletedEvent, self._handle_note_processing_completed
        )
        logger.info(
            f"WebhookService started with {len(self.config.endpoints)} endpoint(s)."
        )

    async def stop(self) -> None:
        """Close the shared HTTP client session."""
        if self._session is not None:
            await self._session.close()
            self._session = None
        self._endpoints_by_user = {}

    def _matching_endpoints(
        self, user_id: int, event_name: str
    ) -> list[WebhookEndpointConfig]:
        """Return configured endpoints subscribed to `event_name` for `user_id`."""
        return [
            ep
            for ep in self._endpoints_by_user.get(user_id, ())
            if not ep.events or event_name in ep.events
        ]

    async def _handle_note_updated(self, event: Event) -> None:
        """Translate a NoteUpdatedEvent into a note.sync_completed webhook."""
        if not isinstance(event, NoteUpdatedEvent):
            return
        payload = NoteSyncCompletedPayload(
            event=EVENT_NOTE_SYNC_COMPLETED,
            timestamp=int(time.time()),
            file=WebhookFileVO(
                id=event.file_id,
                name=PurePosixPath(event.file_path).name,
                path=event.file_path,
            ),
        )
        await self.dispatch(payload, user_id=event.user_id)

    async def _handle_note_processing_completed(self, event: Event) -> None:
        """Translate a NoteProcessingCompletedEvent into a note.processing_completed webhook."""
        if not isinstance(event, NoteProcessingCompletedEvent):
            return
        payload = NoteProcessingCompletedPayload(
            event=EVENT_NOTE_PROCESSING_COMPLETED,
            timestamp=int(time.time()),
            file=WebhookFileVO(
                id=event.file_id,
                name=PurePosixPath(event.file_path).name,
                path=event.file_path,
            ),
        )
        await self.dispatch(payload, user_id=event.user_id)

    async def dispatch(self, payload: WebhookPayload, *, user_id: int) -> None:
        """Send `payload` to every configured endpoint subscribed to `payload.event` for `user_id`.

        An endpoint with no `events` configured receives every event for its
        configured user. Never raises: endpoints are notified concurrently and
        independently, and one endpoint failing has no effect on delivery to
        the others.
        """
        event_name = payload.event
        endpoints = self._matching_endpoints(user_id, event_name)
        if not endpoints:
            return
        body = str(payload.to_json()).encode("utf-8")
        results = await asyncio.gather(
            *(self._send(endpoint, event_name, body) for endpoint in endpoints),
            return_exceptions=True,
        )
        for endpoint, result in zip(endpoints, results, strict=True):
            if isinstance(result, BaseException):
                safe_url = _redact_url(endpoint.url)
                logger.error(
                    f"Webhook {event_name} to {safe_url} raised "
                    f"{type(result).__name__}: {result}"
                )

    async def _send(
        self,
        endpoint: WebhookEndpointConfig,
        event_name: str,
        body: bytes,
    ) -> None:
        """POST `body` to a single endpoint, retrying transient failures.

        Redirects (3xx) are not followed and client errors (4xx) are not
        retried. Network errors, timeouts, and server errors (5xx) are retried
        up to MAX_ATTEMPTS with a linear backoff. All failures are logged
        (without the secret, signature, or URL credentials/query parameters)
        and swallowed.
        """
        if self._session is None:
            raise RuntimeError("WebhookService is not started")

        headers = {"Content-Type": "application/json", EVENT_HEADER: event_name}
        if endpoint.secret:
            headers[SIGNATURE_HEADER] = sign_payload(endpoint.secret, body)

        safe_url = _redact_url(endpoint.url)
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
        session = self._session
        async with self._semaphore:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    async with session.post(
                        endpoint.url,
                        data=body,
                        headers=headers,
                        timeout=timeout,
                        allow_redirects=False,
                    ) as response:
                        if 200 <= response.status < 300:
                            return
                        if response.status < 500:
                            logger.warning(
                                f"Webhook {event_name} to {safe_url} rejected "
                                f"with status {response.status}; not retrying."
                            )
                            return
                        logger.warning(
                            f"Webhook {event_name} to {safe_url} failed with "
                            f"status {response.status} (attempt {attempt}/{MAX_ATTEMPTS})."
                        )
                except (aiohttp.ClientError, TimeoutError) as e:
                    logger.warning(
                        f"Webhook {event_name} to {safe_url} failed: "
                        f"{type(e).__name__} (attempt {attempt}/{MAX_ATTEMPTS})."
                    )

                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)

        logger.error(
            f"Webhook {event_name} to {safe_url} failed after "
            f"{MAX_ATTEMPTS} attempts; giving up."
        )
