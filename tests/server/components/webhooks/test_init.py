"""Unit tests for `supernote.server.components.webhooks.WebhooksComponent`."""

from __future__ import annotations

import pytest

from supernote.server.components.webhooks import WebhooksComponent
from supernote.server.core import Component, ComponentLoader, ServerCore
from supernote.server.events import NoteUpdatedEvent

VALID_WEBHOOKS_CONFIG = {
    "enabled": True,
    "endpoints": [
        {
            "url": "http://127.0.0.1:9999/hook",
            "user": "user@example.com",
            "secret": "test-secret",
        }
    ],
}


async def test_webhooks_component_lifecycle(component_core: ServerCore) -> None:
    component = WebhooksComponent()
    assert isinstance(component, Component)
    assert component.domain == "webhooks"
    assert component.dependencies == ()
    assert component.platforms == ()

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(component_core, {"webhooks": VALID_WEBHOOKS_CONFIG})
    assert NoteUpdatedEvent not in component_core.event_bus._subscribers

    await loader.async_start_all(component_core)
    assert len(component_core.event_bus._subscribers[NoteUpdatedEvent]) == 1

    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_webhooks_component_stop_after_setup_only(
    component_core: ServerCore,
) -> None:
    loader = ComponentLoader()
    loader.register(WebhooksComponent())

    await loader.async_setup_all(component_core, {"webhooks": VALID_WEBHOOKS_CONFIG})
    await loader.async_stop_all(component_core)


async def test_webhooks_component_validates_config_on_setup(
    component_core: ServerCore,
) -> None:
    loader = ComponentLoader()
    loader.register(WebhooksComponent())

    with pytest.raises(ValueError, match="endpoints"):
        await loader.async_setup_all(
            component_core,
            {
                "webhooks": {
                    "enabled": True,
                    "endpoints": [{"url": "ftp://invalid", "user": "user@example.com"}],
                }
            },
        )
