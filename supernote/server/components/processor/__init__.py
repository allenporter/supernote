"""Background notebook processing pipeline and platform host (`ProcessorComponent`).

Runs the asynchronous, event-driven pipeline that processes uploaded `.note`
notebooks in the background—hashing pages, rendering cached PNGs, and running
downstream AI stages such as OCR, embeddings, and summaries. Rather than
hardcoding every stage in one place, this component hosts the `"processor"`
platform so other components can contribute `ProcessorModule` stages via
``<component>.processor:async_setup_processor(core, registrar)``, which are
compiled into a dependency-ordered `TaskGraph` during startup.

It also exposes user-facing processing status/metadata endpoints, admin queue
controls and reprocessing endpoints, and the `get_page_image` MCP tool.

Provides `ProcessorComponent`, `ProcessorService`, `ProcessorRegistrar`,
`ProcessorModule`, `TaskGraph`, `TaskScope`, and `PROCESSOR_SERVICE_KEY`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aiohttp import web

from supernote.server.core import ServerCore

from .base import (
    DuplicateTaskError,
    MissingTaskDependencyError,
    ProcessorModule,
    TaskDependencyCycleError,
    TaskGraph,
    TaskGraphError,
    TaskScope,
)
from .service import ProcessorService

__all__ = [
    "PROCESSOR_SERVICE_KEY",
    "DuplicateTaskError",
    "MissingTaskDependencyError",
    "ProcessorComponent",
    "ProcessorModule",
    "ProcessorRegistrar",
    "ProcessorService",
    "TaskDependencyCycleError",
    "TaskGraph",
    "TaskGraphError",
    "TaskScope",
]

PROCESSOR_SERVICE_KEY: web.AppKey[ProcessorService] = web.AppKey("processor_service")


class ProcessorRegistrar:
    """Registrar passed into ``<component>.processor:async_setup_processor(core, registrar)``."""

    def __init__(self) -> None:
        self._modules: list[ProcessorModule] = []
        self._finalized = False

    def register_module(self, module: ProcessorModule) -> None:
        """Register a `ProcessorModule` stage to be compiled into the pipeline `TaskGraph`."""
        if self._finalized:
            raise RuntimeError(
                "Cannot register processor module after platforms are finalized"
            )
        self._modules.append(module)

    def mark_finalized(self) -> None:
        """Lock the registrar against further module registrations."""
        self._finalized = True

    @property
    def modules(self) -> tuple[ProcessorModule, ...]:
        """Registered processor modules in registration order."""
        return tuple(self._modules)


class ProcessorComponent:
    """Platform host component managing `ProcessorService` and the `"processor"` platform."""

    domain = "processor"
    dependencies: tuple[str, ...] = ("ai",)
    platforms: tuple[str, ...] = ("http", "mcp", "processor")
    hosted_platforms: tuple[str, ...] = ("processor",)

    def __init__(self) -> None:
        self._service: ProcessorService | None = None
        self._registrar: ProcessorRegistrar | None = None

    def get_platform_registrar(self) -> ProcessorRegistrar:
        """Return the `ProcessorRegistrar` initialized during `async_setup`."""
        assert self._registrar is not None
        return self._registrar

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Instantiate `ProcessorService`, bind `PROCESSOR_SERVICE_KEY`, and initialize `ProcessorRegistrar`."""
        service = ProcessorService(
            event_bus=core.event_bus,
            session_manager=core.session_manager,
            file_service=core.file_service,
            coordination_service=core.coordination,
        )
        core.app[PROCESSOR_SERVICE_KEY] = service
        self._service = service
        self._registrar = ProcessorRegistrar()

    async def async_finalize_platforms(self, core: ServerCore) -> None:
        """Compile all registered processor modules into the service's `TaskGraph`."""
        assert self._service is not None
        registrar = self.get_platform_registrar()
        registrar.mark_finalized()
        self._service.set_modules(registrar.modules)

    async def async_start(self, core: ServerCore) -> None:
        """Start `ProcessorService` workers, event subscriptions, and recovery polling."""
        assert self._service is not None
        await self._service.start()

    async def async_stop(self, core: ServerCore) -> None:
        """Idempotently stop `ProcessorService` workers and release references."""
        if self._service is not None:
            await self._service.stop()
            self._service = None
        self._registrar = None
