"""Main `aiohttp` application factory, core service wiring, and lifecycle hooks.

`create_app` initializes core infrastructure (`ServerCore`, `ComponentLoader`,
database/VFS/auth/processor services, and core route tables) and lazily registers
enabled built-in vertical components (`ai`, `apple`, `events`, `fake_ai`,
`gemini`, `http`, `mcp`, `metrics`, `oauth`, `openai`, `processor`, `schedule`,
`search`, `socketio`, `summary`, `transcript`, `web_ui`, `webhooks`) via
`supernote.server.components.load_builtin_components`.

During `on_startup`, the server runs Alembic migrations, initializes `UrlSigner`,
runs `component_loader.async_setup_all` and the `http` platform pass
(`async_load_platform("http", ...)` + `http_registrar.apply_to_app`), and starts
background workers (`ProcessorService` and all enabled components).
See `supernote.guides.bootstrap_guide` and `supernote.guides.architecture`.
"""

import asyncio
import logging
import os
from typing import Any

from aiohttp import web

from supernote.models.user import UserRegisterDTO
from supernote.server.db.migrations import run_migrations
from supernote.server.keys import (
    BLOB_STORAGE_KEY,
    COMPONENT_LOADER_KEY,
    CONFIG_KEY,
    CONVERSION_SERVICE_KEY,
    COORDINATION_SERVICE_KEY,
    CORE_KEY,
    EVENT_BUS_KEY,
    FILE_SERVICE_KEY,
    INTEGRITY_SERVICE_KEY,
    PROCESSOR_SERVICE_KEY,
    RATE_LIMITER_KEY,
    SESSION_MANAGER_KEY,
    URL_SIGNER_KEY,
    USER_SERVICE_KEY,
)

from .components import load_builtin_components
from .config import AuthConfig, ServerConfig
from .constants import MAX_UPLOAD_SIZE
from .core import ComponentLoader, ServerCore
from .db.session import DatabaseSessionManager
from .events import LocalEventBus
from .routes import (
    admin,
    auth,
    extended,
    file_device,
    file_web,
    oss,
    system,
)
from .services.blob import LocalBlobStorage
from .services.conversion import ConversionService
from .services.coordination import CoordinationService, SqliteCoordinationService
from .services.file import FileService
from .services.integrity import IntegrityService
from .services.user import UserService
from .trace import ACCESS_LOG_FORMAT, SanitizedAccessLogger
from .utils.hashing import get_md5_hash
from .utils.rate_limit import RateLimiter
from .utils.url_signer import UrlSigner

logger = logging.getLogger(__name__)


def create_db_session_manager(db_url: str) -> DatabaseSessionManager:
    return DatabaseSessionManager(db_url)


def create_coordination_service(
    session_manager: DatabaseSessionManager,
) -> SqliteCoordinationService:
    return SqliteCoordinationService(session_manager)


def create_user_service(
    auth_config: AuthConfig,
    coordination_service: CoordinationService,
    session_manager: DatabaseSessionManager,
) -> UserService:
    return UserService(auth_config, coordination_service, session_manager)


def create_app(config: ServerConfig) -> web.Application:
    app = web.Application(client_max_size=MAX_UPLOAD_SIZE)
    app[CONFIG_KEY] = config

    # Initialize services
    blob_storage = LocalBlobStorage(config.storage_root)

    session_manager = create_db_session_manager(config.db_url)
    coordination_service = create_coordination_service(session_manager)

    app[SESSION_MANAGER_KEY] = session_manager
    app[COORDINATION_SERVICE_KEY] = coordination_service
    app[BLOB_STORAGE_KEY] = blob_storage
    event_bus = LocalEventBus()
    app[EVENT_BUS_KEY] = event_bus

    user_service = create_user_service(
        config.auth, coordination_service, session_manager
    )
    file_service = FileService(
        config.storage_root,
        blob_storage,
        user_service,
        session_manager,
        event_bus,
        default_user_quota=config.default_user_quota,
    )
    app[USER_SERVICE_KEY] = user_service
    app[FILE_SERVICE_KEY] = file_service
    app[INTEGRITY_SERVICE_KEY] = IntegrityService(session_manager, blob_storage)

    app[RATE_LIMITER_KEY] = RateLimiter(coordination_service)

    core = ServerCore(
        config=config,
        app=app,
        event_bus=event_bus,
        session_manager=session_manager,
        coordination=coordination_service,
        blob_storage=blob_storage,
        user_service=user_service,
        file_service=file_service,
    )
    component_loader = ComponentLoader()
    app[CORE_KEY] = core
    app[COMPONENT_LOADER_KEY] = component_loader

    configured_ai_providers = {
        config.ai.provider_type(m.provider).strip().lower()
        for m in (
            config.ai.ocr,
            config.ai.summary,
            config.ai.embedding,
            config.ai.text,
        )
        if m is not None
    }
    component_configs = {
        "apple": {"enabled": "apple" in configured_ai_providers},
        "fake_ai": {"enabled": "fake" in configured_ai_providers},
        "gemini": {"enabled": "gemini" in configured_ai_providers},
        "mcp": {"enabled": config.mcp_enabled},
        "metrics": {"enabled": config.metrics_enabled},
        "oauth": {"enabled": config.mcp_enabled},
        "openai": {"enabled": "openai" in configured_ai_providers},
        "web_ui": {"enabled": config.web_enabled},
        "webhooks": config.webhooks,
    }
    load_builtin_components(component_loader, component_configs)

    # Register routes
    app.add_routes(system.routes)
    app.add_routes(admin.routes)
    app.add_routes(auth.routes)
    app.add_routes(file_web.routes)
    app.add_routes(file_device.routes)
    app.add_routes(oss.routes)
    app.add_routes(extended.routes)

    async def on_startup_handler(app: web.Application) -> None:
        logger.info("Running database migrations...")
        await asyncio.to_thread(run_migrations, config.db_url, config=config)

        secret_key = await user_service.get_secret_key()
        app[URL_SIGNER_KEY] = UrlSigner(secret_key, coordination_service)

        if config.ephemeral:
            await bootstrap_ephemeral_user(app)

        await component_loader.async_setup_all(core, component_configs)
        app[CONVERSION_SERVICE_KEY] = ConversionService(
            session_manager=session_manager,
            blob_storage=blob_storage,
            user_service=user_service,
            processor_service=app[PROCESSOR_SERVICE_KEY],
        )
        await component_loader.async_load_all_platforms(core)

        logger.info("Starting background services...")
        await file_service.start()
        await component_loader.async_start_all(core)
        logger.info("Startup sequence complete.")

    app.on_startup.append(on_startup_handler)

    async def on_shutdown_handler(app: web.Application) -> None:
        await component_loader.async_stop_all(core)
        await session_manager.close()

    app.on_shutdown.append(on_shutdown_handler)

    async def on_cleanup_handler(app: web.Application) -> None:
        await component_loader.async_stop_all(core)

    app.on_cleanup.append(on_cleanup_handler)

    return app


async def bootstrap_ephemeral_user(app: web.Application) -> None:
    """Create a default admin user and system folders for ephemeral mode if not present."""
    user_service = app[USER_SERVICE_KEY]
    if not await user_service.check_user_exists("debug@example.com"):
        logger.info("Creating default user debug@example.com / password")
        await user_service.register(
            UserRegisterDTO(
                email="debug@example.com",
                password=get_md5_hash("password"),
                user_name="Debug User",
            )
        )


def run(args: Any) -> None:
    FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
    env_level = getattr(
        logging,
        os.getenv("SUPERNOTE_LOG_LEVEL", "INFO").strip().upper(),
        logging.INFO,
    )
    logging.basicConfig(level=env_level, format=FORMAT, force=True)

    config_dir = getattr(args, "config_dir", None)
    config = ServerConfig.load(config_dir)

    level = getattr(logging, config.log_level)
    logging.getLogger().setLevel(level)
    noisy_level = max(level, logging.INFO)
    logging.getLogger("aiosqlite").setLevel(noisy_level)
    logging.getLogger("asyncio").setLevel(noisy_level)

    app = create_app(config)

    web.run_app(
        app,
        host=config.host,
        port=config.port,
        access_log_class=SanitizedAccessLogger,
        access_log=logging.getLogger("aiohttp.access"),
        access_log_format=ACCESS_LOG_FORMAT,
    )
