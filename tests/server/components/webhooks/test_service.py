"""Component and HMAC tests for `supernote.server.components.webhooks`."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import ANY, patch

import aiohttp
import pytest
from aiohttp import web
from pytest_aiohttp import AiohttpClient

from supernote.models.events import DomainEntityType, DomainEventType
from supernote.models.user import UserRegisterDTO
from supernote.server.components.webhooks.service import (
    EVENT_HEADER,
    MAX_ATTEMPTS,
    MAX_CONCURRENT_REQUESTS,
    SIGNATURE_HEADER,
    sign_payload,
    verify_signature,
)
from supernote.server.core import ServerCore
from supernote.server.events import (
    NotePageTranscribedEvent,
    NoteProcessingCompletedEvent,
    ScheduleTaskCreatedEvent,
    VfsItemCreatedEvent,
)
from supernote.server.services.user import UserService
from tests.fixtures.server import TEST_USERNAME
from tests.server.components.conftest import LoadComponents


class _StallResponse:
    """Sentinel response: the receiver stalls until released on teardown."""


STALL = _StallResponse()


class WebhookReceiver:
    """A real aiohttp server standing in for a third-party webhook receiver."""

    def __init__(self) -> None:
        self.url = ""
        self.redirect_target_url = ""
        self.calls: list[dict[str, Any]] = []
        self._responses: list[int | _StallResponse] = []
        self._release_stalls = asyncio.Event()

    def queue_responses(self, *responses: int | _StallResponse) -> None:
        """Set the canned per-POST responses, consumed in order (default: 200)."""
        self._responses = list(responses)

    def release_stalls(self) -> None:
        """Unblock any stalled server-side handlers prior to server teardown."""
        self._release_stalls.set()

    async def handle(self, request: web.Request) -> web.Response:
        body = await request.read()
        self.calls.append(
            {"url": str(request.url), "data": body, "headers": dict(request.headers)}
        )
        response = self._responses.pop(0) if self._responses else 200
        if isinstance(response, _StallResponse):
            await self._release_stalls.wait()
            return web.Response(status=200)
        if 300 <= response < 400:
            return web.Response(
                status=response, headers={"Location": self.redirect_target_url}
            )
        return web.Response(status=response)


@pytest.fixture
async def webhook_receiver(
    aiohttp_client: AiohttpClient,
) -> AsyncGenerator[WebhookReceiver]:
    """Spin up a real aiohttp server to receive webhook POSTs in tests."""
    receiver = WebhookReceiver()
    app = web.Application()
    app.router.add_post("/webhook", receiver.handle)
    app.router.add_post("/redirected", receiver.handle)
    client = await aiohttp_client(app)
    receiver.url = str(client.make_url("/webhook"))
    receiver.redirect_target_url = str(client.make_url("/redirected"))
    try:
        yield receiver
    finally:
        receiver.release_stalls()


@pytest.fixture(autouse=True)
def no_retry_backoff() -> Generator[None]:
    """Use zeroed retry backoff so retry tests stay fast."""
    with patch(
        "supernote.server.components.webhooks.service.RETRY_BACKOFF_SECONDS", 0.0
    ):
        yield


def _endpoint_dict(url: str, **overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "url": url,
        "user": TEST_USERNAME,
        "secret": "top-secret",
        "events": [DomainEventType.VFS_CREATED],
    }
    defaults.update(overrides)
    return defaults


def _vfs_created(
    user_id: int,
    item_id: int = 42,
    full_path: str = "Note/a.note",
    name: str | None = None,
) -> VfsItemCreatedEvent:
    return VfsItemCreatedEvent(
        user_id=user_id,
        item_id=item_id,
        parent_id=0,
        name=name or full_path.rsplit("/", 1)[-1],
        full_path=full_path,
        is_folder=False,
    )


def _webhooks_cfg(
    *endpoints: dict[str, Any], enabled: bool = True
) -> dict[str, dict[str, Any]]:
    return {"webhooks": {"enabled": enabled, "endpoints": list(endpoints)}}


def test_sign_payload_is_deterministic_hmac_sha256() -> None:
    body = b'{"eventType": "vfs.created"}'
    signature = sign_payload("my-secret", body)

    expected = hmac.new(b"my-secret", body, hashlib.sha256).hexdigest()
    assert signature == f"sha256={expected}"


def test_verify_signature_accepts_valid_signature() -> None:
    body = b'{"eventType": "vfs.created"}'
    signature = sign_payload("my-secret", body)

    assert verify_signature("my-secret", body, signature) is True


def test_verify_signature_rejects_tampered_body() -> None:
    body = b'{"eventType": "vfs.created"}'
    signature = sign_payload("my-secret", body)

    assert (
        verify_signature("my-secret", b'{"eventType": "tampered"}', signature) is False
    )


def test_verify_signature_rejects_wrong_secret() -> None:
    body = b'{"eventType": "vfs.created"}'
    signature = sign_payload("my-secret", body)

    assert verify_signature("wrong-secret", body, signature) is False


def test_verify_signature_rejects_malformed_or_empty_inputs() -> None:
    body = b'{"eventType": "vfs.created"}'
    signature = sign_payload("my-secret", body)

    assert verify_signature("", body, signature) is False
    assert verify_signature("my-secret", body, "") is False
    assert (
        verify_signature("my-secret", body, signature.removeprefix("sha256=")) is False
    )


async def test_domain_event_sends_signed_post_to_subscribed_endpoint(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
) -> None:
    await load_components(
        "webhooks",
        configs=_webhooks_cfg(_endpoint_dict(webhook_receiver.url)),
    )
    await component_core.event_bus.publish(
        _vfs_created(test_user_id, item_id=42, full_path="Note/Daily/2026-08-04.note")
    )
    await component_core.event_bus.wait_idle()

    assert len(webhook_receiver.calls) == 1
    call = webhook_receiver.calls[0]
    assert call["url"] == webhook_receiver.url
    assert call["headers"][EVENT_HEADER] == DomainEventType.VFS_CREATED
    assert call["headers"][SIGNATURE_HEADER] == sign_payload("top-secret", call["data"])
    body = json.loads(call["data"])
    assert body == {
        "seq": ANY,
        "timestamp": ANY,
        "eventType": DomainEventType.VFS_CREATED,
        "actor": "user:web",
        "entityType": DomainEntityType.FILE,
        "entityId": "42",
        "relatedFileId": "42",
        "payload": {
            "item_id": "42",
            "parent_id": "0",
            "name": "2026-08-04.note",
            "full_path": "Note/Daily/2026-08-04.note",
            "is_folder": False,
            "size": 0,
            "md5": None,
        },
    }
    assert isinstance(body["timestamp"], int)
    assert body["seq"].isdigit()


async def test_note_processing_completed_event_triggers_webhook(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
) -> None:
    await load_components(
        "webhooks",
        configs=_webhooks_cfg(
            _endpoint_dict(
                webhook_receiver.url,
                events=[DomainEventType.NOTE_PROCESSING_COMPLETED],
            )
        ),
    )
    await component_core.event_bus.publish(
        NoteProcessingCompletedEvent(
            file_id=42, user_id=test_user_id, file_path="Note/Daily/2026-08-04.note"
        )
    )
    await component_core.event_bus.wait_idle()

    assert len(webhook_receiver.calls) == 1
    assert (
        webhook_receiver.calls[0]["headers"][EVENT_HEADER]
        == DomainEventType.NOTE_PROCESSING_COMPLETED
    )
    body = json.loads(webhook_receiver.calls[0]["data"])
    assert body == {
        "seq": ANY,
        "timestamp": ANY,
        "eventType": DomainEventType.NOTE_PROCESSING_COMPLETED,
        "actor": "system:processor",
        "entityType": DomainEntityType.FILE,
        "entityId": "42",
        "relatedFileId": "42",
        "payload": {
            "file_id": "42",
            "file_path": "Note/Daily/2026-08-04.note",
        },
    }
    assert isinstance(body["timestamp"], int)


async def test_namespace_prefix_wildcard_filters_events(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
) -> None:
    await load_components(
        "webhooks",
        configs=_webhooks_cfg(_endpoint_dict(webhook_receiver.url, events=["note.*"])),
    )
    await component_core.event_bus.publish(_vfs_created(test_user_id, item_id=1))
    await component_core.event_bus.publish(
        NoteProcessingCompletedEvent(
            file_id=42, user_id=test_user_id, file_path="Note/a.note"
        )
    )
    await component_core.event_bus.publish(
        NotePageTranscribedEvent(
            file_id=42,
            user_id=test_user_id,
            file_path="Note/a.note",
            page_id="p1",
            page_index=0,
            text_content="hello",
        )
    )
    await component_core.event_bus.publish(
        ScheduleTaskCreatedEvent(user_id=test_user_id, task_id="t1", title="Buy milk")
    )
    await component_core.event_bus.wait_idle()

    assert {c["headers"][EVENT_HEADER] for c in webhook_receiver.calls} == {
        DomainEventType.NOTE_PROCESSING_COMPLETED,
        DomainEventType.NOTE_PAGE_TRANSCRIBED,
    }


async def test_star_wildcard_receives_all_domain_events(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
) -> None:
    await load_components(
        "webhooks",
        configs=_webhooks_cfg(_endpoint_dict(webhook_receiver.url, events=["*"])),
    )
    await component_core.event_bus.publish(_vfs_created(test_user_id, item_id=1))
    await component_core.event_bus.publish(
        ScheduleTaskCreatedEvent(user_id=test_user_id, task_id="t1", title="Buy milk")
    )
    await component_core.event_bus.wait_idle()

    assert {c["headers"][EVENT_HEADER] for c in webhook_receiver.calls} == {
        DomainEventType.VFS_CREATED,
        DomainEventType.SCHEDULE_TASK_CREATED,
    }


async def test_skips_endpoints_not_subscribed_to_event(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
) -> None:
    await load_components(
        "webhooks",
        configs=_webhooks_cfg(
            _endpoint_dict(
                webhook_receiver.url,
                events=[DomainEventType.NOTE_PROCESSING_COMPLETED],
            )
        ),
    )
    await component_core.event_bus.publish(_vfs_created(test_user_id))
    await component_core.event_bus.wait_idle()
    assert webhook_receiver.calls == []


async def test_endpoint_with_no_events_receives_all_events(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
) -> None:
    """An endpoint with no `events` configured defaults to receiving all events."""
    await load_components(
        "webhooks",
        configs=_webhooks_cfg(_endpoint_dict(webhook_receiver.url, events=[])),
    )
    await component_core.event_bus.publish(_vfs_created(test_user_id))
    await component_core.event_bus.publish(
        NoteProcessingCompletedEvent(
            file_id=42, user_id=test_user_id, file_path="Note/a.note"
        )
    )
    await component_core.event_bus.wait_idle()
    assert len(webhook_receiver.calls) == 2
    assert {c["headers"][EVENT_HEADER] for c in webhook_receiver.calls} == {
        DomainEventType.VFS_CREATED,
        DomainEventType.NOTE_PROCESSING_COMPLETED,
    }


async def test_omits_signature_header_when_no_secret(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
) -> None:
    await load_components(
        "webhooks",
        configs=_webhooks_cfg(_endpoint_dict(webhook_receiver.url, secret="")),
    )
    await component_core.event_bus.publish(_vfs_created(test_user_id))
    await component_core.event_bus.wait_idle()
    assert len(webhook_receiver.calls) == 1
    assert SIGNATURE_HEADER not in webhook_receiver.calls[0]["headers"]


async def test_does_not_subscribe_when_disabled(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
) -> None:
    await load_components(
        "webhooks",
        configs=_webhooks_cfg(_endpoint_dict(webhook_receiver.url), enabled=False),
    )
    await component_core.event_bus.publish(_vfs_created(test_user_id, item_id=1))
    await component_core.event_bus.wait_idle()
    assert webhook_receiver.calls == []


async def test_retries_repeated_server_errors_without_raising(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
) -> None:
    webhook_receiver.queue_responses(500, 500, 500)
    await load_components(
        "webhooks",
        configs=_webhooks_cfg(_endpoint_dict(webhook_receiver.url)),
    )
    await component_core.event_bus.publish(_vfs_created(test_user_id))
    await component_core.event_bus.wait_idle()
    assert len(webhook_receiver.calls) == MAX_ATTEMPTS


async def test_retries_timeouts_without_raising(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
) -> None:
    webhook_receiver.queue_responses(STALL, STALL, STALL)
    await load_components(
        "webhooks",
        configs=_webhooks_cfg(_endpoint_dict(webhook_receiver.url)),
    )
    with patch(
        "supernote.server.components.webhooks.service.REQUEST_TIMEOUT_SECONDS", 0.05
    ):
        await component_core.event_bus.publish(_vfs_created(test_user_id))
        await component_core.event_bus.wait_idle()

    assert len(webhook_receiver.calls) == MAX_ATTEMPTS


async def test_does_not_retry_client_errors(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
) -> None:
    webhook_receiver.queue_responses(404, 200, 200)
    await load_components(
        "webhooks",
        configs=_webhooks_cfg(_endpoint_dict(webhook_receiver.url)),
    )
    await component_core.event_bus.publish(_vfs_created(test_user_id))
    await component_core.event_bus.wait_idle()
    assert len(webhook_receiver.calls) == 1


async def test_does_not_follow_redirects_or_retry_3xx(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    webhook_receiver.queue_responses(307, 200, 200)
    await load_components(
        "webhooks",
        configs=_webhooks_cfg(_endpoint_dict(webhook_receiver.url)),
    )
    with caplog.at_level("WARNING"):
        await component_core.event_bus.publish(_vfs_created(test_user_id))
        await component_core.event_bus.wait_idle()

    assert len(webhook_receiver.calls) == 1
    assert webhook_receiver.calls[0]["url"] == webhook_receiver.url
    assert "rejected with status 307" in caplog.text


async def test_recovers_after_transient_failure(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
) -> None:
    webhook_receiver.queue_responses(500, 200)
    await load_components(
        "webhooks",
        configs=_webhooks_cfg(_endpoint_dict(webhook_receiver.url)),
    )
    await component_core.event_bus.publish(_vfs_created(test_user_id))
    await component_core.event_bus.wait_idle()
    assert len(webhook_receiver.calls) == 2


async def test_does_not_leak_secret_or_full_signature_in_logs(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    webhook_receiver.queue_responses(500, 500, 500)
    await load_components(
        "webhooks",
        configs=_webhooks_cfg(
            _endpoint_dict(webhook_receiver.url, secret="super-secret-value")
        ),
    )
    with caplog.at_level("WARNING"):
        await component_core.event_bus.publish(_vfs_created(test_user_id))
        await component_core.event_bus.wait_idle()

    assert caplog.text
    assert "super-secret-value" not in caplog.text
    full_sig = sign_payload("super-secret-value", webhook_receiver.calls[0]["data"])
    assert full_sig not in caplog.text


async def test_unexpected_error_is_isolated_per_endpoint(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unexpected error on one endpoint is logged and does not block sibling endpoints."""
    await load_components(
        "webhooks",
        configs=_webhooks_cfg(
            _endpoint_dict("https://example.invalid/hook"),
            _endpoint_dict(webhook_receiver.url, secret=""),
        ),
    )
    with (
        caplog.at_level("ERROR"),
        patch(
            "supernote.server.components.webhooks.service.sign_payload",
            side_effect=RuntimeError("unexpected signing failure"),
        ),
    ):
        await component_core.event_bus.publish(_vfs_created(test_user_id))
        await component_core.event_bus.wait_idle()

    assert "raised RuntimeError" in caplog.text
    assert len(webhook_receiver.calls) == 1


async def test_reuses_client_session_across_events_and_closes_on_stop(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
) -> None:
    created_sessions: list[aiohttp.ClientSession] = []
    real_client_session = aiohttp.ClientSession

    def tracking_session(*args: Any, **kwargs: Any) -> aiohttp.ClientSession:
        session = real_client_session(*args, **kwargs)
        created_sessions.append(session)
        return session

    with patch(
        "supernote.server.components.webhooks.service.aiohttp.ClientSession",
        side_effect=tracking_session,
    ):
        loader = await load_components(
            "webhooks",
            configs=_webhooks_cfg(_endpoint_dict(webhook_receiver.url)),
        )
        await component_core.event_bus.publish(_vfs_created(test_user_id, item_id=1))
        await component_core.event_bus.publish(
            _vfs_created(test_user_id, item_id=2, full_path="Note/b.note")
        )
        await component_core.event_bus.wait_idle()

        assert len(webhook_receiver.calls) == 2
        assert len(created_sessions) == 1
        assert not created_sessions[0].closed

        await loader.async_stop_all(component_core)
        assert created_sessions[0].closed


async def test_bounds_concurrent_requests_via_semaphore(
    component_core: ServerCore,
    load_components: LoadComponents,
    aiohttp_client: AiohttpClient,
    test_user_id: int,
) -> None:
    active = 0
    max_active = 0
    reached_limit = asyncio.Event()
    release = asyncio.Event()
    total_endpoints = MAX_CONCURRENT_REQUESTS + 2

    async def slow_handler(request: web.Request) -> web.Response:
        nonlocal active, max_active
        await request.read()
        active += 1
        max_active = max(max_active, active)
        if active == MAX_CONCURRENT_REQUESTS:
            reached_limit.set()
        await release.wait()
        active -= 1
        return web.Response(status=200)

    app = web.Application()
    app.router.add_post("/webhook", slow_handler)
    client = await aiohttp_client(app)
    url = str(client.make_url("/webhook"))

    endpoints = [_endpoint_dict(url) for _ in range(total_endpoints)]
    await load_components("webhooks", configs=_webhooks_cfg(*endpoints))

    try:
        await component_core.event_bus.publish(_vfs_created(test_user_id))
        async with asyncio.timeout(2.0):
            await reached_limit.wait()
        assert max_active == MAX_CONCURRENT_REQUESTS
    finally:
        release.set()

    await component_core.event_bus.wait_idle()
    assert max_active == MAX_CONCURRENT_REQUESTS


async def test_redacts_url_credentials_and_query_params_in_logs(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    webhook_receiver.queue_responses(403, 500, 500, 500)
    url_with_secrets = (
        webhook_receiver.url.replace("http://", "http://hook-user:hook-password@")
        + "?token=secret-query-token#secret-fragment"
    )
    await load_components(
        "webhooks",
        configs=_webhooks_cfg(
            _endpoint_dict(url_with_secrets), _endpoint_dict(url_with_secrets)
        ),
    )
    with caplog.at_level("WARNING"):
        await component_core.event_bus.publish(_vfs_created(test_user_id))
        await component_core.event_bus.wait_idle()

    assert "hook-user" not in caplog.text
    assert "hook-password" not in caplog.text
    assert "secret-query-token" not in caplog.text
    assert "secret-fragment" not in caplog.text
    assert webhook_receiver.url in caplog.text


async def test_redacts_url_secrets_on_unexpected_exception(
    component_core: ServerCore,
    load_components: LoadComponents,
    test_user_id: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await load_components(
        "webhooks",
        configs=_webhooks_cfg(
            _endpoint_dict(
                "https://api-user:api-pass@example.invalid/hook?api_key=top-secret-key"
            )
        ),
    )
    with (
        caplog.at_level("ERROR"),
        patch(
            "supernote.server.components.webhooks.service.sign_payload",
            side_effect=RuntimeError("unexpected signing failure"),
        ),
    ):
        await component_core.event_bus.publish(_vfs_created(test_user_id))
        await component_core.event_bus.wait_idle()

    assert "api-user" not in caplog.text
    assert "api-pass" not in caplog.text
    assert "top-secret-key" not in caplog.text
    assert "https://example.invalid/hook" in caplog.text


async def test_domain_event_respects_endpoint_user_filter(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    user_service: UserService,
    test_user_id: int,
) -> None:
    alice = await user_service.create_user(
        UserRegisterDTO(
            email="alice@example.com",
            password="a" * 32,
            user_name="Alice",
        )
    )
    assert alice.id is not None

    await load_components(
        "webhooks",
        configs=_webhooks_cfg(
            _endpoint_dict(webhook_receiver.url, user="alice@example.com")
        ),
    )

    # Another user (not Alice) should not trigger Alice's endpoint.
    await component_core.event_bus.publish(
        _vfs_created(test_user_id, item_id=99, full_path="Note/Bob/Private.note")
    )
    await component_core.event_bus.wait_idle()
    assert webhook_receiver.calls == []

    # Alice triggers Alice's endpoint.
    await component_core.event_bus.publish(
        _vfs_created(alice.id, item_id=42, full_path="Note/Alice/Daily.note")
    )
    await component_core.event_bus.wait_idle()
    assert len(webhook_receiver.calls) == 1
    body = json.loads(webhook_receiver.calls[0]["data"])
    assert body == {
        "seq": ANY,
        "timestamp": ANY,
        "eventType": DomainEventType.VFS_CREATED,
        "actor": "user:web",
        "entityType": DomainEntityType.FILE,
        "entityId": "42",
        "relatedFileId": "42",
        "payload": {
            "item_id": "42",
            "parent_id": "0",
            "name": "Daily.note",
            "full_path": "Note/Alice/Daily.note",
            "is_folder": False,
            "size": 0,
            "md5": None,
        },
    }


async def test_start_skips_endpoint_when_user_not_found(
    component_core: ServerCore,
    load_components: LoadComponents,
    webhook_receiver: WebhookReceiver,
    test_user_id: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING"):
        await load_components(
            "webhooks",
            configs=_webhooks_cfg(
                _endpoint_dict(webhook_receiver.url, user="missing@example.com")
            ),
        )
        await component_core.event_bus.publish(_vfs_created(test_user_id))
        await component_core.event_bus.wait_idle()

    assert webhook_receiver.calls == []
    assert "missing@example.com" in caplog.text
