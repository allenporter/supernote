"""Typed `aiohttp.web.AppKey` registry for core server application and request state.

This module centralizes core `web.AppKey` constants (`CONFIG_KEY`, `CORE_KEY`,
`SESSION_MANAGER_KEY`, `FILE_SERVICE_KEY`, `USER_SERVICE_KEY`, etc.) populated
during `supernote.server.app.create_app` startup and consumed by core routes
and components. Component-owned service keys live inside their owning component
packages under `supernote.server.components`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from .config import ServerConfig
    from .core import ComponentLoader, ServerCore
    from .db.session import DatabaseSessionManager
    from .events import LocalEventBus
    from .services.blob import BlobStorage
    from .services.coordination import CoordinationService
    from .services.file import FileService
    from .services.user import UserService
    from .utils.rate_limit import RateLimiter
    from .utils.url_signer import UrlSigner

CONFIG_KEY: web.AppKey[ServerConfig] = web.AppKey("config")
CORE_KEY: web.AppKey[ServerCore] = web.AppKey("core")
COMPONENT_LOADER_KEY: web.AppKey[ComponentLoader] = web.AppKey("component_loader")
SESSION_MANAGER_KEY: web.AppKey[DatabaseSessionManager] = web.AppKey("session_manager")
COORDINATION_SERVICE_KEY: web.AppKey[CoordinationService] = web.AppKey(
    "coordination_service"
)
BLOB_STORAGE_KEY: web.AppKey[BlobStorage] = web.AppKey("blob_storage")
EVENT_BUS_KEY: web.AppKey[LocalEventBus] = web.AppKey("event_bus")
USER_SERVICE_KEY: web.AppKey[UserService] = web.AppKey("user_service")
FILE_SERVICE_KEY: web.AppKey[FileService] = web.AppKey("file_service")
RATE_LIMITER_KEY: web.AppKey[RateLimiter] = web.AppKey("rate_limiter")
URL_SIGNER_KEY: web.AppKey[UrlSigner] = web.AppKey("url_signer")

REQUEST_USER_KEY: web.RequestKey[str] = web.RequestKey("user")
REQUEST_EQUIPMENT_NO_KEY: web.RequestKey[str | None] = web.RequestKey("equipment_no")
REQUEST_ACTOR_KEY: web.RequestKey[str] = web.RequestKey("actor")
