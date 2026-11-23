"""Server core host, component protocol, and topological lifecycle loader.

Defines `ServerCore` (the strongly-typed host for core server infrastructure),
the `Component` protocol for built-in vertical components and external plugins,
and `ComponentLoader` for deterministic dependency resolution and lifecycle
orchestration (`async_setup`, `async_start`, `async_stop`).
"""

from __future__ import annotations

import heapq
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from aiohttp import web

    from .config import ServerConfig
    from .db.session import DatabaseSessionManager
    from .events import LocalEventBus
    from .services.blob import BlobStorage
    from .services.coordination import CoordinationService
    from .services.file import FileService
    from .services.user import UserService

logger = logging.getLogger(__name__)

_DOMAIN_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


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
    def version(self) -> str:
        """Component version string."""
        ...

    @property
    def dependencies(self) -> Sequence[str]:
        """Domain identifiers that must set up and start before this component."""
        ...

    async def async_setup(self, core: ServerCore) -> None:
        """Register routes, event subscriptions, and UI extensions before startup."""
        ...

    async def async_start(self, core: ServerCore) -> None:
        """Start background workers and external connections during app startup."""
        ...

    async def async_stop(self, core: ServerCore) -> None:
        """Stop background work and release resources idempotently on shutdown."""
        ...


class ComponentLoader:
    """Deterministic topological loader and lifecycle orchestrator for components."""

    def __init__(self) -> None:
        self._components: dict[str, Component] = {}
        self._setup_completed: list[Component] = []
        self._started: list[Component] = []
        self._is_setup = False

    @property
    def components(self) -> tuple[Component, ...]:
        """Return registered components in registration order."""
        return tuple(self._components.values())

    def get(self, domain: str) -> Component | None:
        """Return the registered component for ``domain``, if present."""
        return self._components.get(domain)

    def register(self, component: Component) -> None:
        """Register a component after validating its domain and uniqueness."""
        domain = component.domain
        if not isinstance(domain, str) or not _DOMAIN_PATTERN.fullmatch(domain):
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
                if dep == domain:
                    raise DependencyCycleError((domain, domain))

        reg_index = {domain: idx for idx, domain in enumerate(self._components)}
        in_degree: dict[str, int] = {domain: 0 for domain in self._components}
        dependents: dict[str, list[str]] = {domain: [] for domain in self._components}

        for domain, comp in self._components.items():
            for dep in dict.fromkeys(comp.dependencies):
                dependents[dep].append(domain)
                in_degree[domain] += 1

        ready = [(reg_index[d], d) for d, deg in in_degree.items() if deg == 0]
        heapq.heapify(ready)
        ordered: list[str] = []

        while ready:
            _, current = heapq.heappop(ready)
            ordered.append(current)
            for dependent in dependents[current]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    heapq.heappush(ready, (reg_index[dependent], dependent))

        if len(ordered) != len(self._components):
            remaining = {d for d in self._components if d not in set(ordered)}
            raise DependencyCycleError(self._find_cycle(remaining))

        return tuple(self._components[d] for d in ordered)

    def _find_cycle(self, candidates: set[str]) -> tuple[str, ...]:
        """Extract a deterministic cycle path among unresolved candidate domains."""
        state: dict[str, int] = {}  # 0/absent=unvisited, 1=visiting, 2=visited
        stack: list[str] = []

        def dfs(node: str) -> tuple[str, ...] | None:
            state[node] = 1
            stack.append(node)
            for dep in self._components[node].dependencies:
                if dep not in candidates:
                    continue
                if state.get(dep) == 1:
                    return tuple([*stack[stack.index(dep) :], dep])
                if state.get(dep, 0) == 0:
                    if cycle := dfs(dep):
                        return cycle
            stack.pop()
            state[node] = 2
            return None

        for domain in self._components:
            if domain in candidates and state.get(domain, 0) == 0:
                if cycle := dfs(domain):
                    return cycle
        raise ComponentError("Unresolved dependency cycle")  # pragma: no cover

    async def async_setup_all(self, core: ServerCore) -> None:
        """Set up all registered components in topological order."""
        ordered = self.resolve_order()
        self._setup_completed.clear()
        self._is_setup = False
        try:
            for comp in ordered:
                await comp.async_setup(core)
                self._setup_completed.append(comp)
            self._is_setup = True
        except Exception:
            await _best_effort_stop(reversed(self._setup_completed), core)
            self._setup_completed.clear()
            raise

    async def async_start_all(self, core: ServerCore) -> None:
        """Start set-up components in topological order with reverse rollback on error."""
        if self._components and not self._is_setup:
            raise ComponentError(
                "Components must complete async_setup_all before async_start_all"
            )
        self._started.clear()
        for comp in self._setup_completed:
            try:
                await comp.async_start(core)
                self._started.append(comp)
            except Exception:
                await _best_effort_stop([comp, *reversed(self._started)], core)
                self._started.clear()
                raise

    async def async_stop_all(self, core: ServerCore) -> None:
        """Idempotently stop started components in reverse topological order."""
        to_stop = list(reversed(self._started))
        self._started.clear()
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


@dataclass
class ServerCore:
    """Strongly-typed core host shared with all server components."""

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
    loader: ComponentLoader = field(default_factory=ComponentLoader)
    """Topological component loader and lifecycle orchestrator."""

    def register_component(self, component: Component) -> None:
        """Register a component with this core's loader."""
        self.loader.register(component)

    def get_component(self, domain: str) -> Component | None:
        """Return the registered component for ``domain``, if present."""
        return self.loader.get(domain)

    @property
    def components(self) -> tuple[Component, ...]:
        """Return registered components in registration order."""
        return self.loader.components

    def resolve_components(self) -> tuple[Component, ...]:
        """Resolve deterministic topological order for registered components."""
        return self.loader.resolve_order()

    async def async_setup(self) -> None:
        """Set up all registered components against this core."""
        await self.loader.async_setup_all(self)

    async def async_start(self) -> None:
        """Start all set-up components against this core."""
        await self.loader.async_start_all(self)

    async def async_stop(self) -> None:
        """Idempotently stop all started components in reverse dependency order."""
        await self.loader.async_stop_all(self)
