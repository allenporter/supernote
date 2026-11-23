"""Unit tests for `supernote.server.components.webhooks.WebhooksComponent`."""

from __future__ import annotations

import pytest
from aiohttp import web

from supernote.server.components.webhooks import WebhooksComponent
from supernote.server.config import ServerConfig
from supernote.server.core import Component, ComponentLoader, ServerCore
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus, NoteUpdatedEvent
from supernote.server.services.blob import BlobStorage
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.file import FileService
from supernote.server.services.user import UserService

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


@pytest.fixture
def webhooks_core(
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    blob_storage: BlobStorage,
    user_service: UserService,
    file_service: FileService,
) -> ServerCore:
    """Create a `ServerCore` backed by shared test fixtures."""
    return ServerCore(
        config=server_config,
        app=web.Application(),
        event_bus=LocalEventBus(),
        session_manager=session_manager,
        coordination=coordination_service,
        blob_storage=blob_storage,
        user_service=user_service,
        file_service=file_service,
    )


async def test_webhooks_component_lifecycle(webhooks_core: ServerCore) -> None:
    component = WebhooksComponent()
    assert isinstance(component, Component)
    assert component.domain == "webhooks"
    assert component.dependencies == ()

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(webhooks_core, {"webhooks": VALID_WEBHOOKS_CONFIG})
    assert NoteUpdatedEvent not in webhooks_core.event_bus._subscribers

    await loader.async_start_all(webhooks_core)
    assert len(webhooks_core.event_bus._subscribers[NoteUpdatedEvent]) == 1

    await loader.async_stop_all(webhooks_core)
    await loader.async_stop_all(webhooks_core)


async def test_webhooks_component_stop_after_setup_only(
    webhooks_core: ServerCore,
) -> None:
    loader = ComponentLoader()
    loader.register(WebhooksComponent())

    await loader.async_setup_all(webhooks_core, {"webhooks": VALID_WEBHOOKS_CONFIG})
    await loader.async_stop_all(webhooks_core)


async def test_webhooks_component_validates_config_on_setup(
    webhooks_core: ServerCore,
) -> None:
    loader = ComponentLoader()
    loader.register(WebhooksComponent())

    with pytest.raises(ValueError, match="endpoints"):
        await loader.async_setup_all(
            webhooks_core,
            {
                "webhooks": {
                    "enabled": True,
                    "endpoints": [{"url": "ftp://invalid", "user": "user@example.com"}],
                }
            },
        )
