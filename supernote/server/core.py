"""Server core host, component protocol, and topological lifecycle loader.

Defines `ServerCore` (the immutable, strongly-typed host for core server
infrastructure), the `Component` protocol for built-in vertical components and
external plugins, and `ComponentLoader` for deterministic dependency resolution
and lifecycle orchestration (`async_setup`, `async_start`, `async_stop`).
"""

from __future__ import annotations

import graphlib
import heapq
import importlib
import logging
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from aiohttp import web

    from .config import ServerConfig
    from .db.session import DatabaseSessionManager
    from .events import LocalEventBus
    from .services.blob import BlobStorage
    from .services.coordination import CoordinationService
    from .services.file import FileService
    from .services.user import UserService

__all__ = [
    "Component",
    "ComponentError",
    "ComponentLoader",
    "DependencyCycleError",
    "DuplicateComponentError",
    "MissingDependencyError",
    "PlatformHost",
    "ServerCore",
]

logger = logging.getLogger(__name__)

_DOMAIN_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class _LifecycleState(Enum):
    IDLE = "idle"
    SETUP = "setup"
    STARTED = "started"
    STOPPED = "stopped"


class ComponentError(Exception):
    """Base exception for component registration, dependency, and lifecycle errors."""


class DuplicateComponentError(ComponentError):
    """Raised when registering a component whose domain is already registered."""

    def __init__(self, domain: str) -> None:
        self.domain = domain
        super().__init__(f"Component domain {domain!r} is already registered")


class MissingDependencyError(ComponentError):
    """Raised when a component declares an unregistered dependency."""

    def __init__(self, domain: str, dependency: str) -> None:
        self.domain = domain
        self.dependency = dependency
        super().__init__(
            f"Component {domain!r} depends on missing component {dependency!r}"
        )


class DependencyCycleError(ComponentError):
    """Raised when component dependencies contain a cycle."""

    def __init__(self, cycle: Sequence[str]) -> None:
        self.cycle = tuple(cycle)
        path = " -> ".join(self.cycle)
        super().__init__(f"Dependency cycle detected: {path}")


@runtime_checkable
class Component(Protocol):
    """Uniform lifecycle contract for server components and external plugins."""

    @property
    def domain(self) -> str:
        """Unique lowercase identifier (matching ``^[a-z][a-z0-9_]*$``)."""
        ...

    @property
    def dependencies(self) -> Sequence[str]:
        """Domain identifiers that must set up and start before this component."""
        ...

    @property
    def platforms(self) -> Sequence[str]:
        """Platform names implemented by this component (e.g. ``('http',)``)."""
        ...

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Validate component config and register routes/subscriptions before startup."""
        ...

    async def async_start(self, core: ServerCore) -> None:
        """Start background workers and external connections during app startup."""
        ...

    async def async_stop(self, core: ServerCore) -> None:
        """Stop background work and release resources idempotently on shutdown."""
        ...


@runtime_checkable
class PlatformHost(Protocol):
    """Optional protocol for components that host one or more platforms."""

    @property
    def hosted_platforms(self) -> Sequence[str]:
        """Platform names hosted by this component (e.g. ``('http',)``)."""
        ...

    def get_platform_registrar(self) -> Any:
        """Return the registrar passed into ``async_setup_<platform>(core, registrar)``."""
        ...

    async def async_finalize_platforms(self, core: ServerCore) -> None:
        """Apply or finalize all platform registrations after loading completes."""
        ...


@dataclass(frozen=True)
class ServerCore:
    """Immutable, strongly-typed core host shared with all server components."""

    config: ServerConfig
    """Resolved server configuration."""
    app: web.Application
    """Primary aiohttp web application instance."""
    event_bus: LocalEventBus
    """In-process asynchronous domain event bus."""
    session_manager: DatabaseSessionManager
    """Async SQLAlchemy database session manager."""
    coordination: CoordinationService
    """TTL key-value coordination and lock service."""
    blob_storage: BlobStorage
    """Content-addressable physical blob storage backend."""
    user_service: UserService
    """Core account, device binding, and token verification service."""
    file_service: FileService
    """Core Virtual File System and blob synchronization service."""


class ComponentLoader:
    """Deterministic topological loader and lifecycle orchestrator for components."""

    def __init__(self) -> None:
        self._components: dict[str, Component] = {}
        self._initialized: list[Component] = []
        self._state = _LifecycleState.IDLE

    @property
    def components(self) -> tuple[Component, ...]:
        """Return registered components in registration order."""
        return tuple(self._components.values())

    def get(self, domain: str) -> Component | None:
        """Return the registered component for ``domain``, if present."""
        return self._components.get(domain)

    def register(self, component: Component) -> None:
        """Register a component before setup after validating its domain and uniqueness."""
        if self._state is not _LifecycleState.IDLE:
            raise ComponentError(
                f"Cannot register component after setup (state={self._state.value!r})"
            )
        domain = component.domain
        if not _DOMAIN_PATTERN.fullmatch(domain):
            raise ComponentError(
                f"Component domain {domain!r} must match {_DOMAIN_PATTERN.pattern}"
            )
        if domain in self._components:
            raise DuplicateComponentError(domain)
        self._components[domain] = component

    def resolve_order(self) -> tuple[Component, ...]:
        """Resolve a deterministic topological order preserving registration tie-breaks."""
        for domain, comp in self._components.items():
            for dep in comp.dependencies:
                if dep not in self._components:
                    raise MissingDependencyError(domain, dep)

        reg_index = {domain: idx for idx, domain in enumerate(self._components)}
        sorter: graphlib.TopologicalSorter[str] = graphlib.TopologicalSorter()
        for domain, comp in self._components.items():
            sorter.add(domain, *dict.fromkeys(comp.dependencies))

        try:
            sorter.prepare()
        except graphlib.CycleError as exc:
            raise DependencyCycleError(exc.args[1]) from exc

        ready: list[tuple[int, str]] = []
        ordered: list[Component] = []
        while sorter.is_active():
            for domain in sorter.get_ready():
                heapq.heappush(ready, (reg_index[domain], domain))
            _, current = heapq.heappop(ready)
            ordered.append(self._components[current])
            sorter.done(current)

        return tuple(ordered)

    async def async_setup_all(
        self,
        core: ServerCore,
        configs: Mapping[str, Mapping[str, Any]],
    ) -> None:
        """Set up all registered components in topological order with per-domain config."""
        if self._state is not _LifecycleState.IDLE:
            raise ComponentError(
                f"Cannot run async_setup_all in state {self._state.value!r}"
            )
        ordered = self.resolve_order()
        try:
            for comp in ordered:
                await comp.async_setup(core, configs.get(comp.domain, {}))
                self._initialized.append(comp)
            self._state = _LifecycleState.SETUP
        except BaseException:
            await self.async_stop_all(core)
            raise

    async def async_start_all(self, core: ServerCore) -> None:
        """Start set-up components in topological order with reverse rollback on error."""
        if self._state is not _LifecycleState.SETUP:
            raise ComponentError(
                "Components must complete async_setup_all before async_start_all"
            )
        try:
            for comp in self._initialized:
                await comp.async_start(core)
            self._state = _LifecycleState.STARTED
        except BaseException:
            await self.async_stop_all(core)
            raise

    def iter_platform_components(self, platform: str) -> tuple[Component, ...]:
        """Return initialized components declaring ``platform``, in topological order."""
        return tuple(comp for comp in self._initialized if platform in comp.platforms)

    async def async_load_platform(
        self,
        platform: str,
        core: ServerCore,
        registrar: Any,
    ) -> None:
        """Import and invoke ``async_setup_<platform>(core, registrar)`` for declared components."""
        if self._state is not _LifecycleState.SETUP:
            raise ComponentError(
                f"Cannot load platform {platform!r} in state {self._state.value!r}; "
                "components must complete async_setup_all first"
            )
        setup_attr = f"async_setup_{platform}"
        for comp in self.iter_platform_components(platform):
            comp_module = sys.modules.get(comp.__class__.__module__)
            pkg = (
                comp_module.__package__
                if comp_module is not None and comp_module.__package__
                else comp.__class__.__module__
            )
            module_name = f"{pkg}.{platform}"
            module = importlib.import_module(module_name)
            setup_fn = getattr(module, setup_attr, None)
            if setup_fn is None:
                raise ComponentError(
                    f"Platform module {module_name!r} must define {setup_attr!r}"
                )
            await setup_fn(core, registrar)

    async def async_load_all_platforms(self, core: ServerCore) -> None:
        """Load and finalize every platform declared by initialized `PlatformHost` components."""
        if self._state is not _LifecycleState.SETUP:
            raise ComponentError(
                f"Cannot load platforms in state {self._state.value!r}; "
                "components must complete async_setup_all first"
            )
        try:
            for comp in self._initialized:
                if not isinstance(comp, PlatformHost):
                    continue
                registrar = comp.get_platform_registrar()
                for platform in comp.hosted_platforms:
                    await self.async_load_platform(platform, core, registrar)
                await comp.async_finalize_platforms(core)
        except BaseException:
            await self.async_stop_all(core)
            raise

    async def async_stop_all(self, core: ServerCore) -> None:
        """Idempotently stop all initialized components in reverse topological order."""
        to_stop = list(reversed(self._initialized))
        self._initialized.clear()
        self._state = _LifecycleState.STOPPED
        await _best_effort_stop(to_stop, core)


async def _best_effort_stop(
    components: Iterable[Component],
    core: ServerCore,
) -> None:
    """Stop each component, logging errors so remaining components still tear down."""
    for comp in components:
        try:
            await comp.async_stop(core)
        except Exception:
            logger.exception("Error stopping component %s", comp.domain)
