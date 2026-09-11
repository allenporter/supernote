"""Tests for the outbound webhook dispatcher service."""

import asyncio
import hashlib
import hmac
import json
from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp import web
from pytest_aiohttp import AiohttpClient

from supernote.server.config import WebhookConfig, WebhookEndpointConfig
from supernote.server.events import LocalEventBus, NoteUpdatedEvent
from supernote.server.services.webhook import (
    EVENT_HEADER,
    EVENT_NOTE_SYNC_COMPLETED,
    MAX_ATTEMPTS,
    SIGNATURE_HEADER,
    WebhookService,
    sign_payload,
)


class _StallResponse:
    """Sentinel response: the receiver never replies to the request.

    Used to exercise the dispatcher's own client-side timeout, rather than
    a status code.
    """


STALL = _StallResponse()


class WebhookReceiver:
    """A real aiohttp server standing in for a third-party webhook receiver.

    Records every POST it gets and lets tests script the response to each
    call in turn (an HTTP status, or STALL to force a client timeout).
    Using a real server -- rather than mocking aiohttp.ClientSession --
    exercises the dispatcher's actual request construction, connection
    handling, and timeout/retry behavior end-to-end.
    """

    def __init__(self) -> None:
        self.url = ""
        self.calls: list[dict[str, Any]] = []
        self._responses: list[int | _StallResponse] = []

    def queue_responses(self, *responses: int | _StallResponse) -> None:
        """Set the canned per-POST responses, consumed in order (default: 200)."""
        self._responses = list(responses)

    async def handle(self, request: web.Request) -> web.Response:
        body = await request.read()
        self.calls.append(
            {"url": str(request.url), "data": body, "headers": dict(request.headers)}
        )
        response = self._responses.pop(0) if self._responses else 200
        if isinstance(response, _StallResponse):
            # Outlives the (patched, short) client request timeout used by
            # every test that queues this, so the client sees a real
            # asyncio.TimeoutError instead of a canned status.
            await asyncio.sleep(2)
            return web.Response(status=200)
        return web.Response(status=response)


@pytest.fixture
async def webhook_receiver(aiohttp_client: AiohttpClient) -> WebhookReceiver:
    """Spin up a real aiohttp server to receive webhook POSTs in tests."""
    receiver = WebhookReceiver()
    app = web.Application()
    app.router.add_post("/webhook", receiver.handle)
    client = await aiohttp_client(app)
    receiver.url = str(client.make_url("/webhook"))
    return receiver


@pytest.fixture(autouse=True)
def no_retry_backoff() -> Generator[None]:
    """Use a real (but zeroed-out) asyncio.sleep for retry backoff so the
    suite stays fast without mocking asyncio.sleep globally.
    """
    with patch("supernote.server.services.webhook.RETRY_BACKOFF_SECONDS", 0.0):
        yield


async def _drain_event_loop(iterations: int = 20) -> None:
    """Let scheduled asyncio tasks (e.g. LocalEventBus.publish's fire-and-forget
    handler task, and the child tasks asyncio.gather creates for each webhook
    endpoint) actually run to completion before asserting on their effects.
    """
    for _ in range(iterations):
        await asyncio.sleep(0)


def _endpoint(url: str, **overrides: Any) -> WebhookEndpointConfig:
    defaults: dict[str, Any] = {
        "url": url,
        "secret": "top-secret",
        "events": [EVENT_NOTE_SYNC_COMPLETED],
    }
    defaults.update(overrides)
    return WebhookEndpointConfig(**defaults)


def test_sign_payload_is_deterministic_hmac_sha256() -> None:
    body = b'{"event": "note.sync_completed"}'
    signature = sign_payload("my-secret", body)

    expected = hmac.new(b"my-secret", body, hashlib.sha256).hexdigest()
    assert signature == f"sha256={expected}"


async def test_dispatch_sends_signed_post_to_subscribed_endpoint(
    webhook_receiver: WebhookReceiver,
) -> None:
    endpoint = _endpoint(webhook_receiver.url)
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus())

    payload = {"event": EVENT_NOTE_SYNC_COMPLETED, "user_id": 1}
    await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, payload)

    assert len(webhook_receiver.calls) == 1
    call = webhook_receiver.calls[0]
    assert call["url"] == endpoint.url
    assert json.loads(call["data"]) == payload
    assert call["headers"][EVENT_HEADER] == EVENT_NOTE_SYNC_COMPLETED
    assert call["headers"][SIGNATURE_HEADER] == sign_payload(
        endpoint.secret, call["data"]
    )


async def test_dispatch_skips_endpoints_not_subscribed_to_event(
    webhook_receiver: WebhookReceiver,
) -> None:
    endpoint = _endpoint(webhook_receiver.url, events=["task.created"])
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus())

    await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, {"event": "note.sync_completed"})

    assert webhook_receiver.calls == []


async def test_dispatch_endpoint_with_no_events_receives_everything(
    webhook_receiver: WebhookReceiver,
) -> None:
    """An endpoint with no `events` configured defaults to receiving all events."""
    endpoint = _endpoint(webhook_receiver.url, events=[])
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus())

    await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, {"event": "note.sync_completed"})
    await service.dispatch("task.created", {"event": "task.created"})

    assert len(webhook_receiver.calls) == 2


async def test_dispatch_omits_signature_header_when_no_secret(
    webhook_receiver: WebhookReceiver,
) -> None:
    endpoint = _endpoint(webhook_receiver.url, secret="")
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus())

    await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, {"event": "note.sync_completed"})

    assert SIGNATURE_HEADER not in webhook_receiver.calls[0]["headers"]


async def test_note_updated_event_triggers_note_sync_completed_webhook(
    webhook_receiver: WebhookReceiver,
) -> None:
    endpoint = _endpoint(webhook_receiver.url)
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    event_bus = LocalEventBus()
    service = WebhookService(config, event_bus)
    service.start()

    await event_bus.publish(
        NoteUpdatedEvent(file_id=42, user_id=7, file_path="Note/Daily/2026-08-04.note")
    )
    # LocalEventBus dispatches via asyncio.create_task; let it run.
    await _drain_event_loop()

    assert len(webhook_receiver.calls) == 1
    body = json.loads(webhook_receiver.calls[0]["data"])
    assert body["event"] == EVENT_NOTE_SYNC_COMPLETED
    assert body["file"] == {"id": 42, "path": "Note/Daily/2026-08-04.note"}
    assert "timestamp" in body
    # The internal, per-user database ID must never leave the server.
    assert "user_id" not in body


async def test_start_does_not_subscribe_when_disabled(
    webhook_receiver: WebhookReceiver,
) -> None:
    config = WebhookConfig(enabled=False, endpoints=[_endpoint(webhook_receiver.url)])
    event_bus = LocalEventBus()
    service = WebhookService(config, event_bus)
    service.start()

    await event_bus.publish(
        NoteUpdatedEvent(file_id=1, user_id=1, file_path="Note/a.note")
    )
    await _drain_event_loop()

    assert webhook_receiver.calls == []


async def test_send_does_not_raise_on_repeated_server_errors(
    webhook_receiver: WebhookReceiver,
) -> None:
    webhook_receiver.queue_responses(500, 500, 500)
    endpoint = _endpoint(webhook_receiver.url)
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus())

    # Must not raise even though every attempt fails.
    await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, {"event": "x"})

    assert len(webhook_receiver.calls) == MAX_ATTEMPTS


async def test_send_does_not_raise_on_timeout(
    webhook_receiver: WebhookReceiver,
) -> None:
    webhook_receiver.queue_responses(STALL, STALL, STALL)
    endpoint = _endpoint(webhook_receiver.url)
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus())

    with patch("supernote.server.services.webhook.REQUEST_TIMEOUT_SECONDS", 0.05):
        await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, {"event": "x"})

    assert len(webhook_receiver.calls) == MAX_ATTEMPTS


async def test_send_does_not_retry_client_errors(
    webhook_receiver: WebhookReceiver,
) -> None:
    webhook_receiver.queue_responses(404, 200, 200)
    endpoint = _endpoint(webhook_receiver.url)
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus())

    await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, {"event": "x"})

    assert len(webhook_receiver.calls) == 1


async def test_send_recovers_after_transient_failure(
    webhook_receiver: WebhookReceiver,
) -> None:
    webhook_receiver.queue_responses(500, 200)
    endpoint = _endpoint(webhook_receiver.url)
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus())

    await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, {"event": "x"})

    assert len(webhook_receiver.calls) == 2


async def test_dispatch_does_not_leak_secret_or_full_signature_in_logs(
    webhook_receiver: WebhookReceiver, caplog: pytest.LogCaptureFixture
) -> None:
    webhook_receiver.queue_responses(500, 500, 500)
    endpoint = _endpoint(webhook_receiver.url, secret="super-secret-value")
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus())

    with caplog.at_level("WARNING"):
        await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, {"event": "x"})

    assert "super-secret-value" not in caplog.text


async def test_dispatch_never_raises_on_unexpected_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unexpected error while sending must not reach the caller."""
    config = WebhookConfig(
        enabled=True,
        endpoints=[
            WebhookEndpointConfig(
                url="https://example.invalid/hook",
                events=[EVENT_NOTE_SYNC_COMPLETED],
            ),
        ],
    )
    service = WebhookService(config, LocalEventBus())

    # A payload that cannot be serialized fails outside the retried network
    # errors, so it exercises the unexpected-error path. No real request is
    # ever attempted, so this doesn't need the fake webhook receiver.
    await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, {"bad": object()})

    assert "TypeError" in caplog.text
