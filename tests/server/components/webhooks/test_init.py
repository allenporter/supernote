"""Unit tests for `supernote.server.components.webhooks.WebhooksComponent`."""

from __future__ import annotations

import dataclasses

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


@pytest.fixture
def webhooks_core(
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    blob_storage: BlobStorage,
    user_service: UserService,
    file_service: FileService,
) -> ServerCore:
    """Create a `ServerCore` with webhooks enabled backed by shared test fixtures."""
    config = dataclasses.replace(
        server_config,
        webhooks={
            "enabled": True,
            "endpoints": [
                {
                    "url": "http://127.0.0.1:9999/hook",
                    "user": "user@example.com",
                    "secret": "test-secret",
                }
            ],
        },
    )
    return ServerCore(
        config=config,
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

    await loader.async_setup_all(webhooks_core)
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

    await loader.async_setup_all(webhooks_core)
    await loader.async_stop_all(webhooks_core)


async def test_webhooks_component_validates_config_on_setup(
    webhooks_core: ServerCore,
) -> None:
    invalid_core = dataclasses.replace(
        webhooks_core,
        config=dataclasses.replace(
            webhooks_core.config,
            webhooks={
                "enabled": True,
                "endpoints": [{"url": "ftp://invalid", "user": "user@example.com"}],
            },
        ),
    )
    loader = ComponentLoader()
    loader.register(WebhooksComponent())

    with pytest.raises(ValueError, match="endpoints"):
        await loader.async_setup_all(invalid_core)
