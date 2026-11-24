"""Note processing pipeline component and platform host (`ProcessorComponent`, `ProcessorRegistrar`).

Hosts the `"processor"` platform so built-in components and external plugins can
contribute `ProcessorModule` stages via `<component>.processor:async_setup_processor(core, registrar)`.
During `async_finalize_platforms`, all registered stages are validated and compiled
into a topological `TaskGraph` on `ProcessorService`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore
from supernote.server.keys import PROCESSOR_SERVICE_KEY

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
    platforms: tuple[str, ...] = ("http", "processor")
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
