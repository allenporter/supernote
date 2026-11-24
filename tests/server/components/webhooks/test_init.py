"""Lifecycle tests for `supernote.server.components.webhooks.WebhooksComponent`."""

from __future__ import annotations

import json
from typing import Any

import pytest
from aiohttp import web
from pytest_aiohttp import AiohttpClient

from supernote.server.components.webhooks import WebhooksComponent
from supernote.server.core import Component, ComponentLoader, ServerCore
from supernote.server.events import NoteUpdatedEvent
from tests.fixtures.server import TEST_USERNAME


def _webhooks_config(url: str = "http://127.0.0.1:9999/hook") -> dict[str, Any]:
    return {
        "webhooks": {
            "enabled": True,
            "endpoints": [
                {
                    "url": url,
                    "user": TEST_USERNAME,
                    "secret": "test-secret",
                }
            ],
        }
    }


async def test_webhooks_component_lifecycle(
    component_core: ServerCore,
    aiohttp_client: AiohttpClient,
    test_user_id: int,
) -> None:
    received_file_ids: list[int] = []

    async def handle_hook(request: web.Request) -> web.Response:
        payload = json.loads(await request.read())
        received_file_ids.append(payload["file"]["id"])
        return web.Response(status=200)

    receiver_app = web.Application()
    receiver_app.router.add_post("/hook", handle_hook)
    receiver_client = await aiohttp_client(receiver_app)
    config = _webhooks_config(str(receiver_client.make_url("/hook")))

    component = WebhooksComponent()
    assert isinstance(component, Component)
    assert component.domain == "webhooks"
    assert component.dependencies == ()
    assert component.platforms == ()

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(component_core, config)
    await component_core.event_bus.publish(
        NoteUpdatedEvent(file_id=1, user_id=test_user_id, file_path="Note/before.note")
    )
    await component_core.event_bus.wait_idle()
    assert received_file_ids == []

    await loader.async_start_all(component_core)
    await component_core.event_bus.publish(
        NoteUpdatedEvent(file_id=2, user_id=test_user_id, file_path="Note/after.note")
    )
    await component_core.event_bus.wait_idle()
    assert received_file_ids == [2]

    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_webhooks_component_stop_after_setup_only(
    component_core: ServerCore,
) -> None:
    loader = ComponentLoader()
    loader.register(WebhooksComponent())

    await loader.async_setup_all(component_core, _webhooks_config())
    await loader.async_stop_all(component_core)


async def test_webhooks_component_validates_config_on_setup(
    component_core: ServerCore,
) -> None:
    loader = ComponentLoader()
    loader.register(WebhooksComponent())

    with pytest.raises(ValueError, match="endpoints"):
        await loader.async_setup_all(
            component_core,
            _webhooks_config("ftp://invalid"),
        )
