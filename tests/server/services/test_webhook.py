"""Tests for the outbound webhook dispatcher service."""

import asyncio
import hashlib
import hmac
import json
from typing import Any

import pytest

from supernote.server.config import WebhookConfig, WebhookEndpointConfig
from supernote.server.events import LocalEventBus, NoteUpdatedEvent
from supernote.server.services import webhook as webhook_module
from supernote.server.services.webhook import (
    EVENT_HEADER,
    EVENT_NOTE_SYNC_COMPLETED,
    MAX_ATTEMPTS,
    SIGNATURE_HEADER,
    WebhookService,
    sign_payload,
    verify_signature,
)


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeResponseCtx:
    """Async context manager returned by `session.post(...)`."""

    def __init__(self, result: int | BaseException) -> None:
        self._result = result

    async def __aenter__(self) -> _FakeResponse:
        if isinstance(self._result, BaseException):
            raise self._result
        return _FakeResponse(self._result)

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeTransport:
    """Records every POST made across (possibly many) fake sessions.

    `results` is consumed in order, one entry per POST call. If it runs out,
    subsequent calls default to a 200 response.
    """

    def __init__(self) -> None:
        self._results: list[int | BaseException] = []
        self.calls: list[dict[str, Any]] = []

    def queue_results(self, *results: int | BaseException) -> None:
        """Set the canned per-POST results, consumed in order."""
        self._results = list(results)

    def new_session(self, **_: Any) -> "_FakeClientSession":
        return _FakeClientSession(self)

    def next_result(self) -> int | BaseException:
        if self._results:
            return self._results.pop(0)
        return 200


class _FakeClientSession:
    def __init__(self, transport: _FakeTransport) -> None:
        self._transport = transport

    async def __aenter__(self) -> "_FakeClientSession":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    def post(self, url: str, data: bytes, headers: dict[str, str]) -> _FakeResponseCtx:
        self._transport.calls.append({"url": url, "data": data, "headers": headers})
        return _FakeResponseCtx(self._transport.next_result())


@pytest.fixture
def fake_transport(monkeypatch: pytest.MonkeyPatch) -> _FakeTransport:
    """Patch aiohttp.ClientSession used by the webhook module with a fake."""
    transport = _FakeTransport()
    monkeypatch.setattr(
        webhook_module.aiohttp, "ClientSession", lambda **kw: transport.new_session()
    )
    # Retries use a real (but zeroed-out) asyncio.sleep so the suite stays
    # fast without mocking asyncio.sleep globally.
    monkeypatch.setattr(webhook_module, "RETRY_BACKOFF_SECONDS", 0.0)
    return transport


async def _drain_event_loop(iterations: int = 20) -> None:
    """Let scheduled asyncio tasks (e.g. LocalEventBus.publish's fire-and-forget
    handler task, and the child tasks asyncio.gather creates for each webhook
    endpoint) actually run to completion before asserting on their effects.
    """
    for _ in range(iterations):
        await asyncio.sleep(0)


def _endpoint(**overrides: Any) -> WebhookEndpointConfig:
    defaults: dict[str, Any] = {
        "url": "https://example.com/webhook",
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


def test_verify_signature_accepts_matching_signature() -> None:
    body = b"payload-bytes"
    signature = sign_payload("shared-secret", body)
    assert verify_signature("shared-secret", body, signature) is True


def test_verify_signature_rejects_tampered_body() -> None:
    body = b"payload-bytes"
    signature = sign_payload("shared-secret", body)
    assert verify_signature("shared-secret", b"tampered-bytes", signature) is False


def test_verify_signature_rejects_wrong_secret() -> None:
    body = b"payload-bytes"
    signature = sign_payload("shared-secret", body)
    assert verify_signature("wrong-secret", body, signature) is False


async def test_dispatch_sends_signed_post_to_subscribed_endpoint(
    fake_transport: _FakeTransport,
) -> None:
    endpoint = _endpoint()
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus())

    payload = {"event": EVENT_NOTE_SYNC_COMPLETED, "user_id": 1}
    await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, payload)

    assert len(fake_transport.calls) == 1
    call = fake_transport.calls[0]
    assert call["url"] == endpoint.url
    assert json.loads(call["data"]) == payload
    assert call["headers"][EVENT_HEADER] == EVENT_NOTE_SYNC_COMPLETED
    assert call["headers"][SIGNATURE_HEADER] == sign_payload(
        endpoint.secret, call["data"]
    )


async def test_dispatch_skips_endpoints_not_subscribed_to_event(
    fake_transport: _FakeTransport,
) -> None:
    endpoint = _endpoint(events=["task.created"])
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus())

    await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, {"event": "note.sync_completed"})

    assert fake_transport.calls == []


async def test_dispatch_omits_signature_header_when_no_secret(
    fake_transport: _FakeTransport,
) -> None:
    endpoint = _endpoint(secret="")
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus())

    await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, {"event": "note.sync_completed"})

    assert SIGNATURE_HEADER not in fake_transport.calls[0]["headers"]


async def test_note_updated_event_triggers_note_sync_completed_webhook(
    fake_transport: _FakeTransport,
) -> None:
    endpoint = _endpoint()
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    event_bus = LocalEventBus()
    service = WebhookService(config, event_bus)
    service.start()

    await event_bus.publish(
        NoteUpdatedEvent(file_id=42, user_id=7, file_path="Note/Daily/2026-08-04.note")
    )
    # LocalEventBus dispatches via asyncio.create_task; let it run.
    await _drain_event_loop()

    assert len(fake_transport.calls) == 1
    body = json.loads(fake_transport.calls[0]["data"])
    assert body["event"] == EVENT_NOTE_SYNC_COMPLETED
    assert body["user_id"] == 7
    assert body["file"] == {"id": 42, "path": "Note/Daily/2026-08-04.note"}
    assert "timestamp" in body


async def test_start_does_not_subscribe_when_disabled(
    fake_transport: _FakeTransport,
) -> None:
    config = WebhookConfig(enabled=False, endpoints=[_endpoint()])
    event_bus = LocalEventBus()
    service = WebhookService(config, event_bus)
    service.start()

    await event_bus.publish(
        NoteUpdatedEvent(file_id=1, user_id=1, file_path="Note/a.note")
    )
    await _drain_event_loop()

    assert fake_transport.calls == []


async def test_send_does_not_raise_on_repeated_server_errors(
    fake_transport: _FakeTransport,
) -> None:
    fake_transport.queue_results(500, 500, 500)
    endpoint = _endpoint()
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus())

    # Must not raise even though every attempt fails.
    await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, {"event": "x"})

    assert len(fake_transport.calls) == MAX_ATTEMPTS


async def test_send_does_not_raise_on_timeout(fake_transport: _FakeTransport) -> None:
    fake_transport.queue_results(TimeoutError(), TimeoutError(), TimeoutError())
    endpoint = _endpoint()
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus())

    await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, {"event": "x"})

    assert len(fake_transport.calls) == MAX_ATTEMPTS


async def test_send_does_not_retry_client_errors(
    fake_transport: _FakeTransport,
) -> None:
    fake_transport.queue_results(404, 200, 200)
    endpoint = _endpoint()
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus())

    await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, {"event": "x"})

    assert len(fake_transport.calls) == 1


async def test_send_recovers_after_transient_failure(
    fake_transport: _FakeTransport,
) -> None:
    fake_transport.queue_results(500, 200)
    endpoint = _endpoint()
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus())

    await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, {"event": "x"})

    assert len(fake_transport.calls) == 2


async def test_dispatch_does_not_leak_secret_or_full_signature_in_logs(
    fake_transport: _FakeTransport, caplog: pytest.LogCaptureFixture
) -> None:
    fake_transport.queue_results(500, 500, 500)
    endpoint = _endpoint(secret="super-secret-value")
    config = WebhookConfig(enabled=True, endpoints=[endpoint])
    service = WebhookService(config, LocalEventBus())

    with caplog.at_level("WARNING"):
        await service.dispatch(EVENT_NOTE_SYNC_COMPLETED, {"event": "x"})

    assert "super-secret-value" not in caplog.text
