"""Typed `aiohttp.web.AppKey` registry for application and request state.

This module centralizes all `web.AppKey` constants (`CONFIG_KEY`, `SESSION_MANAGER_KEY`,
`FILE_SERVICE_KEY`, `USER_SERVICE_KEY`, `PROCESSOR_SERVICE_KEY`, `SEARCH_SERVICE_KEY`, etc.)
populated during `supernote.server.app.create_app` startup and consumed by route handlers in
`supernote.server.routes`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from .ai.models.embedding import EmbeddingModel
    from .ai.models.ocr import OcrModel
    from .ai.models.summary import SummaryModel
    from .components.http import HttpRegistrar
    from .config import ServerConfig
    from .core import ComponentLoader, ServerCore
    from .db.session import DatabaseSessionManager
    from .events import LocalEventBus
    from .services.blob import BlobStorage
    from .services.conversion import ConversionService
    from .services.coordination import CoordinationService
    from .services.file import FileService
    from .services.integrity import IntegrityService
    from .services.processor import ProcessorService
    from .services.summary import SummaryService
    from .services.user import UserService
    from .utils.rate_limit import RateLimiter
    from .utils.url_signer import UrlSigner

CONFIG_KEY: web.AppKey[ServerConfig] = web.AppKey("config")
CORE_KEY: web.AppKey[ServerCore] = web.AppKey("core")
COMPONENT_LOADER_KEY: web.AppKey[ComponentLoader] = web.AppKey("component_loader")
HTTP_REGISTRAR_KEY: web.AppKey[HttpRegistrar] = web.AppKey("http_registrar")
SESSION_MANAGER_KEY: web.AppKey[DatabaseSessionManager] = web.AppKey("session_manager")
COORDINATION_SERVICE_KEY: web.AppKey[CoordinationService] = web.AppKey(
    "coordination_service"
)
BLOB_STORAGE_KEY: web.AppKey[BlobStorage] = web.AppKey("blob_storage")
EVENT_BUS_KEY: web.AppKey[LocalEventBus] = web.AppKey("event_bus")
USER_SERVICE_KEY: web.AppKey[UserService] = web.AppKey("user_service")
FILE_SERVICE_KEY: web.AppKey[FileService] = web.AppKey("file_service")
INTEGRITY_SERVICE_KEY: web.AppKey[IntegrityService] = web.AppKey("integrity_service")
OCR_MODEL_KEY: web.AppKey[OcrModel | None] = web.AppKey("ocr_model")
SUMMARY_MODEL_KEY: web.AppKey[SummaryModel | None] = web.AppKey("summary_model")
EMBEDDING_MODEL_KEY: web.AppKey[EmbeddingModel | None] = web.AppKey("embedding_model")
SUMMARY_SERVICE_KEY: web.AppKey[SummaryService] = web.AppKey("summary_service")
RATE_LIMITER_KEY: web.AppKey[RateLimiter] = web.AppKey("rate_limiter")
PROCESSOR_SERVICE_KEY: web.AppKey[ProcessorService] = web.AppKey("processor_service")
CONVERSION_SERVICE_KEY: web.AppKey[ConversionService] = web.AppKey("conversion_service")
URL_SIGNER_KEY: web.AppKey[UrlSigner] = web.AppKey("url_signer")

REQUEST_USER_KEY: web.RequestKey[str] = web.RequestKey("user")
REQUEST_EQUIPMENT_NO_KEY: web.RequestKey[str | None] = web.RequestKey("equipment_no")
REQUEST_ACTOR_KEY: web.RequestKey[str] = web.RequestKey("actor")
