"""Server core host, component protocol, and topological lifecycle loader.

Defines `ServerCore` (the immutable, strongly-typed host for core server
infrastructure), the `Component` protocol for built-in vertical components and
external plugins, and `ComponentLoader` for deterministic dependency resolution
and lifecycle orchestration (`async_setup`, `async_start`, `async_stop`).
"""

from __future__ import annotations

import graphlib
import heapq
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from aiohttp import web
    from aiohttp.typedefs import Middleware

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

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Validate component config and register routes/subscriptions before startup."""
        ...

    async def async_start(self, core: ServerCore) -> None:
        """Start background workers and external connections during app startup."""
        ...

    async def async_stop(self, core: ServerCore) -> None:
        """Stop background work and release resources idempotently on shutdown."""
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
    _outer_middlewares: list[Middleware] = field(default_factory=list, repr=False)
    _inner_middlewares: list[Middleware] = field(default_factory=list, repr=False)
    _public_prefixes: list[str] = field(default_factory=list, repr=False)
    _public_resources: list[web.AbstractResource] = field(
        default_factory=list, repr=False
    )
    _known_resource_paths: set[str] = field(default_factory=set, repr=False)

    def register_middleware(
        self,
        middleware: Middleware,
        *,
        pre_auth: bool = False,
    ) -> None:
        """Register an aiohttp middleware to run outside (`pre_auth=True`) or inside auth."""
        if pre_auth:
            self._outer_middlewares.append(middleware)
        else:
            self._inner_middlewares.append(middleware)

    def register_public_prefix(self, prefix: str) -> None:
        """Register a URL path prefix exempted from `jwt_auth_middleware`."""
        if not prefix.startswith("/"):
            raise ValueError(f"Public path prefix must start with '/': {prefix!r}")
        if prefix not in self._public_prefixes:
            self._public_prefixes.append(prefix)

    def register_public_resource(
        self,
        resource: web.AbstractResource,
        *,
        known_paths: Iterable[str] = (),
    ) -> None:
        """Register an aiohttp resource (e.g. ASGI mount) exempted from `jwt_auth_middleware`."""
        if resource not in self._public_resources:
            self._public_resources.append(resource)
        self._known_resource_paths.update(known_paths)

    @property
    def outer_middlewares(self) -> tuple[Middleware, ...]:
        """Middlewares registered to run before trace and auth middlewares."""
        return tuple(self._outer_middlewares)

    @property
    def inner_middlewares(self) -> tuple[Middleware, ...]:
        """Middlewares registered to run after auth and cache-control middlewares."""
        return tuple(self._inner_middlewares)

    @property
    def public_prefixes(self) -> tuple[str, ...]:
        """Registered URL path prefixes exempted from `jwt_auth_middleware`."""
        return tuple(self._public_prefixes)

    @property
    def public_resources(self) -> tuple[web.AbstractResource, ...]:
        """Registered aiohttp resources exempted from `jwt_auth_middleware`."""
        return tuple(self._public_resources)

    @property
    def known_resource_paths(self) -> frozenset[str]:
        """Bounded canonical paths exposed by registered resources for metrics labeling."""
        return frozenset(self._known_resource_paths)


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
