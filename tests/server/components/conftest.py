"""Shared fixtures for vertical server component unit and conformance tests."""

from __future__ import annotations

import pytest
from aiohttp import web

from supernote.server.config import ServerConfig
from supernote.server.core import ServerCore
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus
from supernote.server.keys import (
    EVENT_LOG_SERVICE_KEY,
    SCHEDULE_SERVICE_KEY,
    SEARCH_SERVICE_KEY,
)
from supernote.server.services.blob import BlobStorage
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.event_log import EventLogService
from supernote.server.services.file import FileService
from supernote.server.services.schedule import ScheduleService
from supernote.server.services.search import SearchService
from supernote.server.services.user import UserService


@pytest.fixture
def component_core(
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    blob_storage: BlobStorage,
    user_service: UserService,
    file_service: FileService,
) -> ServerCore:
    """Create a `ServerCore` backed by shared test fixtures for component tests."""
    event_bus = LocalEventBus()
    app = web.Application()
    app[SEARCH_SERVICE_KEY] = SearchService(session_manager, None)
    app[SCHEDULE_SERVICE_KEY] = ScheduleService(session_manager, event_bus=event_bus)
    app[EVENT_LOG_SERVICE_KEY] = EventLogService(
        session_manager=session_manager,
        coordination_service=coordination_service,
        event_bus=event_bus,
    )
    return ServerCore(
        config=server_config,
        app=app,
        event_bus=event_bus,
        session_manager=session_manager,
        coordination=coordination_service,
        blob_storage=blob_storage,
        user_service=user_service,
        file_service=file_service,
    )
