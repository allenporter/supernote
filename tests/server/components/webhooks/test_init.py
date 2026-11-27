"""Lifecycle tests for `supernote.server.components.webhooks.WebhooksComponent`."""

from __future__ import annotations

import json
from typing import Any

import pytest
from aiohttp import web
from pytest_aiohttp import AiohttpClient

from supernote.models.events import DomainEventType
from supernote.server.core import Component, ServerCore
from supernote.server.events import VfsItemCreatedEvent
from tests.fixtures.server import TEST_USERNAME
from tests.server.components.conftest import LoadComponents


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
    load_components: LoadComponents,
    aiohttp_client: AiohttpClient,
    test_user_id: int,
) -> None:
    received_entity_ids: list[str] = []

    async def handle_hook(request: web.Request) -> web.Response:
        payload = json.loads(await request.read())
        assert payload["eventType"] == DomainEventType.FILE_CREATED
        received_entity_ids.append(payload["entityId"])
        return web.Response(status=200)

    receiver_app = web.Application()
    receiver_app.router.add_post("/hook", handle_hook)
    receiver_client = await aiohttp_client(receiver_app)
    config = _webhooks_config(str(receiver_client.make_url("/hook")))

    loader = await load_components("webhooks", configs=config, start=False)
    component = loader.get("webhooks")
    assert isinstance(component, Component)
    assert component.domain == "webhooks"
    assert component.dependencies == ("events",)
    assert component.platforms == ()

    await component_core.event_bus.publish(
        VfsItemCreatedEvent(
            user_id=test_user_id,
            item_id=1,
            parent_id=0,
            name="before.note",
            full_path="Note/before.note",
            is_folder=False,
        )
    )
    await component_core.event_bus.wait_idle()
    assert received_entity_ids == []

    await loader.async_start_all(component_core)
    await component_core.event_bus.publish(
        VfsItemCreatedEvent(
            user_id=test_user_id,
            item_id=2,
            parent_id=0,
            name="after.note",
            full_path="Note/after.note",
            is_folder=False,
        )
    )
    await component_core.event_bus.wait_idle()
    assert received_entity_ids == ["2"]

    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_webhooks_component_stop_after_setup_only(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    loader = await load_components("webhooks", configs=_webhooks_config(), start=False)
    await loader.async_stop_all(component_core)


async def test_webhooks_component_validates_config_on_setup(
    load_components: LoadComponents,
) -> None:
    with pytest.raises(ValueError, match="endpoints"):
        await load_components(
            "webhooks",
            configs=_webhooks_config("ftp://invalid"),
            start=False,
        )
