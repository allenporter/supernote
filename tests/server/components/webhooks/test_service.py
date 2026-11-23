"""Tests for the outbound webhook dispatcher service."""

import asyncio
import hashlib
import hmac
import json
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any
from unittest.mock import ANY, patch

import pytest
from aiohttp import web
from pytest_aiohttp import AiohttpClient

from supernote.models.user import UserRegisterDTO
from supernote.models.webhook import (
    EVENT_NOTE_PROCESSING_COMPLETED,
    EVENT_NOTE_SYNC_COMPLETED,
    NoteSyncCompletedPayload,
    WebhookFileVO,
    WebhookPayload,
)
from supernote.server.components.webhooks.config import (
    WebhookConfig,
    WebhookEndpointConfig,
)
from supernote.server.components.webhooks.service import (
    EVENT_HEADER,
    MAX_ATTEMPTS,
    SIGNATURE_HEADER,
    WebhookService,
    sign_payload,
    verify_signature,
)
from supernote.server.events import (
    LocalEventBus,
    NoteProcessingCompletedEvent,
    NoteUpdatedEvent,
)
from supernote.server.services.user import UserService
from tests.fixtures.server import TEST_USERNAME


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
        self.redirect_target_url = ""
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
        if 300 <= response < 400:
            return web.Response(
                status=response, headers={"Location": self.redirect_target_url}
            )
        return web.Response(status=response)


@pytest.fixture
async def webhook_receiver(aiohttp_client: AiohttpClient) -> WebhookReceiver:
    """Spin up a real aiohttp server to receive webhook POSTs in tests."""
    receiver = WebhookReceiver()
    app = web.Application()
    app.router.add_post("/webhook", receiver.handle)
    app.router.add_post("/redirected", receiver.handle)
    client = await aiohttp_client(app)
    receiver.url = str(client.make_url("/webhook"))
    receiver.redirect_target_url = str(client.make_url("/redirected"))
    return receiver


@pytest.fixture(autouse=True)
def no_retry_backoff() -> Generator[None]:
    """Use a real (but zeroed-out) asyncio.sleep for retry backoff so the
    suite stays fast without mocking asyncio.sleep globally.
    """
    with patch(
        "supernote.server.components.webhooks.service.RETRY_BACKOFF_SECONDS", 0.0
    ):
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
        "user": TEST_USERNAME,
        "secret": "top-secret",
        "events": [EVENT_NOTE_SYNC_COMPLETED],
    }
    defaults.update(overrides)
    return WebhookEndpointConfig(**defaults)


def _sample_payload(event: str = EVENT_NOTE_SYNC_COMPLETED) -> NoteSyncCompletedPayload:
    return NoteSyncCompletedPayload(
        event=event,
        timestamp=1730000000,
        file=WebhookFileVO(
            id=42, name="2026-08-04.note", path="Note/Daily/2026-08-04.note"
        ),
    )


def test_sign_payload_is_deterministic_hmac_sha256() -> None:
    body = b'{"event": "note.sync_completed"}'
    signature = sign_payload("my-secret", body)

    expected = hmac.new(b"my-secret", body, hashlib.sha256).hexdigest()
    assert signature == f"sha256={expected}"


def test_verify_signature_accepts_valid_signature() -> None:
    body = b'{"event": "note.sync_completed"}'
    signature = sign_payload("my-secret", body)

    assert verify_signature("my-secret", body, signature) is True


def test_verify_signature_rejects_tampered_body() -> None:
    body = b'{"event": "note.sync_completed"}'
    signature = sign_payload("my-secret", body)

    assert verify_signature("my-secret", b'{"event": "tampered"}', signature) is False


def test_verify_signature_rejects_wrong_secret() -> None:
    body = b'{"event": "note.sync_completed"}'
    signature = sign_payload("my-secret", body)

    assert verify_signature("wrong-secret", body, signature) is False


def test_verify_signature_rejects_malformed_or_empty_inputs() -> None:
    body = b'{"event": "note.sync_completed"}'
    signature = sign_payload("my-secret", body)

    assert verify_signature("", body, signature) is False
    assert verify_signature("my-secret", body, "") is False
    assert (
        verify_signature("my-secret", body, signature.removeprefix("sha256=")) is False
    )


RunningServiceFactory = Callable[..., AbstractAsyncContextManager[WebhookService]]


@pytest.fixture
def running_service(
    user_service: UserService,
    create_test_user: None,
) -> RunningServiceFactory:
    @asynccontextmanager
    async def _factory(
        config: WebhookConfig,
        event_bus: LocalEventBus | None = None,
    ) -> AsyncGenerator[WebhookService]:
        service = WebhookService(
            config,
            event_bus or LocalEventBus(),
            user_service,
        )
        await service.start()
        try:
            yield service
        finally:
            await service.stop()

    return _factory


async def test_dispatch_sends_signed_post_to_subscribed_endpoint(
    webhook_receiver: WebhookReceiver,
    running_service: RunningServiceFactory,
    test_user_id: int,
) -> None:
    endpoint = _endpoint(webhook_receiver.url)
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    payload = _sample_payload()
    async with running_service(config) as service:
        await service.dispatch(payload, user_id=test_user_id)

    assert len(webhook_receiver.calls) == 1
    call = webhook_receiver.calls[0]
    assert call["url"] == endpoint.url
    assert json.loads(call["data"]) == payload.to_dict()
    assert call["headers"][EVENT_HEADER] == EVENT_NOTE_SYNC_COMPLETED
    assert call["headers"][SIGNATURE_HEADER] == sign_payload(
        endpoint.secret, call["data"]
    )


async def test_dispatch_skips_endpoints_not_subscribed_to_event(
    webhook_receiver: WebhookReceiver,
    running_service: RunningServiceFactory,
    test_user_id: int,
) -> None:
    endpoint = _endpoint(webhook_receiver.url, events=["task.created"])
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    async with running_service(config) as service:
        await service.dispatch(_sample_payload(), user_id=test_user_id)

    assert webhook_receiver.calls == []


async def test_dispatch_endpoint_with_no_events_receives_everything(
    webhook_receiver: WebhookReceiver,
    running_service: RunningServiceFactory,
    test_user_id: int,
) -> None:
    """An endpoint with no `events` configured defaults to receiving all events."""
    endpoint = _endpoint(webhook_receiver.url, events=[])
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    async with running_service(config) as service:
        await service.dispatch(_sample_payload(), user_id=test_user_id)
        await service.dispatch(
            WebhookPayload(event="task.created", timestamp=1730000000),
            user_id=test_user_id,
        )

    assert len(webhook_receiver.calls) == 2


async def test_dispatch_omits_signature_header_when_no_secret(
    webhook_receiver: WebhookReceiver,
    running_service: RunningServiceFactory,
    test_user_id: int,
) -> None:
    endpoint = _endpoint(webhook_receiver.url, secret="")
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    async with running_service(config) as service:
        await service.dispatch(_sample_payload(), user_id=test_user_id)

    assert SIGNATURE_HEADER not in webhook_receiver.calls[0]["headers"]


async def test_note_updated_event_triggers_note_sync_completed_webhook(
    webhook_receiver: WebhookReceiver,
    running_service: RunningServiceFactory,
    test_user_id: int,
) -> None:
    endpoint = _endpoint(webhook_receiver.url)
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    event_bus = LocalEventBus()
    async with running_service(config, event_bus):
        await event_bus.publish(
            NoteUpdatedEvent(
                file_id=42, user_id=test_user_id, file_path="Note/Daily/2026-08-04.note"
            )
        )
        # LocalEventBus dispatches via asyncio.create_task; let it run.
        await _drain_event_loop()

        assert len(webhook_receiver.calls) == 1
        body = json.loads(webhook_receiver.calls[0]["data"])
        assert body == {
            "event": EVENT_NOTE_SYNC_COMPLETED,
            "timestamp": ANY,
            "file": {
                "id": 42,
                "name": "2026-08-04.note",
                "path": "Note/Daily/2026-08-04.note",
            },
        }
        assert isinstance(body["timestamp"], int)


async def test_note_processing_completed_event_triggers_webhook(
    webhook_receiver: WebhookReceiver,
    running_service: RunningServiceFactory,
    test_user_id: int,
) -> None:
    endpoint = _endpoint(webhook_receiver.url, events=[EVENT_NOTE_PROCESSING_COMPLETED])
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    event_bus = LocalEventBus()
    async with running_service(config, event_bus):
        await event_bus.publish(
            NoteProcessingCompletedEvent(
                file_id=42, user_id=test_user_id, file_path="Note/Daily/2026-08-04.note"
            )
        )
        await _drain_event_loop()

        assert len(webhook_receiver.calls) == 1
        body = json.loads(webhook_receiver.calls[0]["data"])
        assert body == {
            "event": EVENT_NOTE_PROCESSING_COMPLETED,
            "timestamp": ANY,
            "file": {
                "id": 42,
                "name": "2026-08-04.note",
                "path": "Note/Daily/2026-08-04.note",
            },
        }
        assert isinstance(body["timestamp"], int)


async def test_start_does_not_subscribe_when_disabled(
    webhook_receiver: WebhookReceiver,
    running_service: RunningServiceFactory,
    test_user_id: int,
) -> None:
    config = WebhookConfig(enabled=False, endpoints=[_endpoint(webhook_receiver.url)])
    event_bus = LocalEventBus()
    async with running_service(config, event_bus):
        await event_bus.publish(
            NoteUpdatedEvent(file_id=1, user_id=test_user_id, file_path="Note/a.note")
        )
        await _drain_event_loop()

    assert webhook_receiver.calls == []


async def test_send_does_not_raise_on_repeated_server_errors(
    webhook_receiver: WebhookReceiver,
    running_service: RunningServiceFactory,
    test_user_id: int,
) -> None:
    webhook_receiver.queue_responses(500, 500, 500)
    endpoint = _endpoint(webhook_receiver.url)
    config = WebhookConfig(enabled=True, endpoints=[endpoint])

    # Must not raise even though every attempt fails.
    async with running_service(config) as service:
        await service.dispatch(_sample_payload(), user_id=test_user_id)

    assert len(webhook_receiver.calls) == MAX_ATTEMPTS


async def test_send_does_not_raise_on_timeout(
    webhook_receiver: WebhookReceiver,
    running_service: RunningServiceFactory,
    test_user_id: int,
) -> None:
    webhook_receiver.queue_responses(STALL, STALL, STALL)
    endpoint = _endpoint(webhook_receiver.url)
    config = WebhookConfig(enabled=True, endpoints=[endpoint])

    async with running_service(config) as service:
        with patch(
            "supernote.server.components.webhooks.service.REQUEST_TIMEOUT_SECONDS", 0.05
        ):
            await service.dispatch(_sample_payload(), user_id=test_user_id)

    assert len(webhook_receiver.calls) == MAX_ATTEMPTS


async def test_send_does_not_retry_client_errors(
    webhook_receiver: WebhookReceiver,
    running_service: RunningServiceFactory,
    test_user_id: int,
) -> None:
    webhook_receiver.queue_responses(404, 200, 200)
    endpoint = _endpoint(webhook_receiver.url)
    config = WebhookConfig(enabled=True, endpoints=[endpoint])

    async with running_service(config) as service:
        await service.dispatch(_sample_payload(), user_id=test_user_id)

    assert len(webhook_receiver.calls) == 1


async def test_send_does_not_follow_redirects_or_retry_3xx(
    webhook_receiver: WebhookReceiver,
    running_service: RunningServiceFactory,
    test_user_id: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    webhook_receiver.queue_responses(307, 200, 200)
    endpoint = _endpoint(webhook_receiver.url)
    config = WebhookConfig(enabled=True, endpoints=[endpoint])

    async with running_service(config) as service:
        with caplog.at_level("WARNING"):
            await service.dispatch(_sample_payload(), user_id=test_user_id)

    assert len(webhook_receiver.calls) == 1
    assert webhook_receiver.calls[0]["url"] == webhook_receiver.url
    assert "rejected with status 307" in caplog.text


async def test_send_recovers_after_transient_failure(
    webhook_receiver: WebhookReceiver,
    running_service: RunningServiceFactory,
    test_user_id: int,
) -> None:
    webhook_receiver.queue_responses(500, 200)
    endpoint = _endpoint(webhook_receiver.url)
    config = WebhookConfig(enabled=True, endpoints=[endpoint])

    async with running_service(config) as service:
        await service.dispatch(_sample_payload(), user_id=test_user_id)

    assert len(webhook_receiver.calls) == 2


async def test_dispatch_does_not_leak_secret_or_full_signature_in_logs(
    webhook_receiver: WebhookReceiver,
    running_service: RunningServiceFactory,
    test_user_id: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    webhook_receiver.queue_responses(500, 500, 500)
    endpoint = _endpoint(webhook_receiver.url, secret="super-secret-value")
    config = WebhookConfig(enabled=True, endpoints=[endpoint])

    async with running_service(config) as service:
        with caplog.at_level("WARNING"):
            await service.dispatch(_sample_payload(), user_id=test_user_id)

    assert "super-secret-value" not in caplog.text


async def test_dispatch_never_raises_on_unexpected_error(
    running_service: RunningServiceFactory,
    test_user_id: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unexpected error while sending must not reach the caller."""
    config = WebhookConfig(
        enabled=True,
        endpoints=[
            WebhookEndpointConfig(
                url="https://example.invalid/hook",
                user=TEST_USERNAME,
                secret="test-secret",
                events=[EVENT_NOTE_SYNC_COMPLETED],
            ),
        ],
    )
    async with running_service(config) as service:
        with patch(
            "supernote.server.components.webhooks.service.sign_payload",
            side_effect=RuntimeError("unexpected signing failure"),
        ):
            await service.dispatch(_sample_payload(), user_id=test_user_id)

    assert "RuntimeError" in caplog.text


async def test_started_service_reuses_client_session_until_stopped(
    webhook_receiver: WebhookReceiver,
    user_service: UserService,
    test_user_id: int,
) -> None:
    endpoint = _endpoint(webhook_receiver.url)
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus(), user_service)
    await service.start()
    try:
        shared_session = service._session
        assert shared_session is not None
        assert not shared_session.closed

        await service.dispatch(_sample_payload(), user_id=test_user_id)
        await service.dispatch(_sample_payload(), user_id=test_user_id)

        assert len(webhook_receiver.calls) == 2
        assert service._session is shared_session
        assert not shared_session.closed
    finally:
        await service.stop()

    assert service._session is None
    assert shared_session.closed


async def test_dispatch_bounds_concurrent_requests_via_semaphore(
    aiohttp_client: AiohttpClient,
    user_service: UserService,
    test_user_id: int,
) -> None:
    active = 0
    max_active = 0
    release = asyncio.Event()

    async def slow_handler(request: web.Request) -> web.Response:
        nonlocal active, max_active
        await request.read()
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        await release.wait()
        active -= 1
        return web.Response(status=200)

    app = web.Application()
    app.router.add_post("/webhook", slow_handler)
    client = await aiohttp_client(app)
    url = str(client.make_url("/webhook"))

    endpoints = [_endpoint(url) for _ in range(4)]
    config = WebhookConfig(enabled=True, endpoints=endpoints)
    service = WebhookService(config, LocalEventBus(), user_service, max_concurrency=2)
    await service.start()
    try:
        dispatch_task = asyncio.create_task(
            service.dispatch(_sample_payload(), user_id=test_user_id)
        )
        await asyncio.sleep(0.05)
        assert max_active == 2
        release.set()
        await dispatch_task
        assert max_active == 2
    finally:
        await service.stop()


async def test_dispatch_redacts_url_credentials_and_query_params_in_logs(
    webhook_receiver: WebhookReceiver,
    running_service: RunningServiceFactory,
    test_user_id: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    webhook_receiver.queue_responses(403, 500, 500, 500)
    url_with_secrets = (
        webhook_receiver.url.replace("http://", "http://hook-user:hook-password@")
        + "?token=secret-query-token#secret-fragment"
    )
    endpoint_4xx = _endpoint(url_with_secrets)
    endpoint_5xx = _endpoint(url_with_secrets)
    config = WebhookConfig(enabled=True, endpoints=[endpoint_4xx, endpoint_5xx])

    async with running_service(config) as service:
        with caplog.at_level("WARNING"):
            await service.dispatch(_sample_payload(), user_id=test_user_id)

    assert "hook-user" not in caplog.text
    assert "hook-password" not in caplog.text
    assert "secret-query-token" not in caplog.text
    assert "secret-fragment" not in caplog.text
    assert webhook_receiver.url in caplog.text


async def test_dispatch_redacts_url_secrets_on_unexpected_exception(
    running_service: RunningServiceFactory,
    test_user_id: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = WebhookConfig(
        enabled=True,
        endpoints=[
            WebhookEndpointConfig(
                url="https://api-user:api-pass@example.invalid/hook?api_key=top-secret-key",
                user=TEST_USERNAME,
                secret="test-secret",
                events=[EVENT_NOTE_SYNC_COMPLETED],
            ),
        ],
    )
    async with running_service(config) as service:
        with patch(
            "supernote.server.components.webhooks.service.sign_payload",
            side_effect=RuntimeError("unexpected signing failure"),
        ):
            await service.dispatch(_sample_payload(), user_id=test_user_id)

    assert "api-user" not in caplog.text
    assert "api-pass" not in caplog.text
    assert "top-secret-key" not in caplog.text
    assert "https://example.invalid/hook" in caplog.text


async def test_note_updated_event_respects_endpoint_user_filter(
    webhook_receiver: WebhookReceiver,
    running_service: RunningServiceFactory,
    user_service: UserService,
) -> None:
    alice = await user_service.create_user(
        UserRegisterDTO(
            email="alice@example.com",
            password="a" * 32,
            user_name="Alice",
        )
    )
    assert alice.id is not None

    alice_endpoint = _endpoint(webhook_receiver.url, user="alice@example.com")
    config = WebhookConfig(enabled=True, endpoints=[alice_endpoint])
    event_bus = LocalEventBus()
    async with running_service(config, event_bus):
        # Another user (not Alice) should not trigger Alice's endpoint.
        await event_bus.publish(
            NoteUpdatedEvent(
                file_id=99, user_id=alice.id + 1, file_path="Note/Bob/Private.note"
            )
        )
        await _drain_event_loop()
        assert webhook_receiver.calls == []

        # Alice triggers Alice's endpoint.
        await event_bus.publish(
            NoteUpdatedEvent(
                file_id=42, user_id=alice.id, file_path="Note/Alice/Daily.note"
            )
        )
        await _drain_event_loop()
        assert len(webhook_receiver.calls) == 1
        body = json.loads(webhook_receiver.calls[0]["data"])
        assert body == {
            "event": EVENT_NOTE_SYNC_COMPLETED,
            "timestamp": ANY,
            "file": {
                "id": 42,
                "name": "Daily.note",
                "path": "Note/Alice/Daily.note",
            },
        }


async def test_start_skips_endpoint_when_user_not_found(
    webhook_receiver: WebhookReceiver,
    running_service: RunningServiceFactory,
    test_user_id: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    endpoint = _endpoint(webhook_receiver.url, user="missing@example.com")
    config = WebhookConfig(enabled=True, endpoints=[endpoint])

    with caplog.at_level("WARNING"):
        async with running_service(config) as service:
            await service.dispatch(_sample_payload(), user_id=test_user_id)

    assert webhook_receiver.calls == []
    assert "missing@example.com" in caplog.text
