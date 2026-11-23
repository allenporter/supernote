"""Unit tests for `supernote.server.core` (`ServerCore`, `Component`, `ComponentLoader`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from aiohttp import web

from supernote.server.config import ServerConfig
from supernote.server.core import (
    Component,
    ComponentError,
    DependencyCycleError,
    DuplicateComponentError,
    MissingDependencyError,
    ServerCore,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus
from supernote.server.services.blob import LocalBlobStorage
from supernote.server.services.coordination import SqliteCoordinationService
from supernote.server.services.file import FileService
from supernote.server.services.user import UserService


@dataclass
class RecordingComponent:
    """Test component recording lifecycle calls and optionally injecting faults."""

    domain: str
    dependencies: tuple[str, ...] = ()
    version: str = "1.0.0"
    events: list[tuple[str, str]] = field(default_factory=list)
    seen_cores: list[ServerCore] = field(default_factory=list)
    fail_on: str | None = None
    fail_stop: bool = False

    async def async_setup(self, core: ServerCore) -> None:
        self.seen_cores.append(core)
        if self.fail_on == "setup":
            raise RuntimeError(f"setup failure in {self.domain}")
        self.events.append(("setup", self.domain))

    async def async_start(self, core: ServerCore) -> None:
        self.seen_cores.append(core)
        if self.fail_on == "start":
            raise RuntimeError(f"start failure in {self.domain}")
        self.events.append(("start", self.domain))

    async def async_stop(self, core: ServerCore) -> None:
        self.seen_cores.append(core)
        self.events.append(("stop", self.domain))
        if self.fail_stop:
            raise RuntimeError(f"stop failure in {self.domain}")


@pytest.fixture
def server_core(tmp_path: Path) -> ServerCore:
    """Create a standalone `ServerCore` backed by temporary storage."""
    config = ServerConfig(storage_dir=str(tmp_path))
    app = web.Application()
    event_bus = LocalEventBus()
    session_manager = DatabaseSessionManager(
        f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}"
    )
    coordination = SqliteCoordinationService(session_manager)
    blob_storage = LocalBlobStorage(tmp_path)
    user_service = UserService(config.auth, coordination, session_manager)
    file_service = FileService(
        tmp_path, blob_storage, user_service, session_manager, event_bus
    )
    return ServerCore(
        config=config,
        app=app,
        event_bus=event_bus,
        session_manager=session_manager,
        coordination=coordination,
        blob_storage=blob_storage,
        user_service=user_service,
        file_service=file_service,
    )


def test_server_core_exposes_typed_services_and_component_accessors(
    server_core: ServerCore,
) -> None:
    comp = RecordingComponent(domain="webhooks")
    assert isinstance(comp, Component)

    server_core.register_component(comp)

    assert server_core.get_component("webhooks") is comp
    assert server_core.get_component("missing") is None
    assert server_core.components == (comp,)
    assert isinstance(server_core.config, ServerConfig)
    assert isinstance(server_core.app, web.Application)
    assert isinstance(server_core.event_bus, LocalEventBus)
    assert isinstance(server_core.session_manager, DatabaseSessionManager)
    assert isinstance(server_core.coordination, SqliteCoordinationService)
    assert isinstance(server_core.blob_storage, LocalBlobStorage)
    assert isinstance(server_core.user_service, UserService)
    assert isinstance(server_core.file_service, FileService)


@pytest.mark.parametrize(
    "bad_domain",
    ["", "   ", "UpperCase", "1leading_digit", "bad-hyphen", "bad/slash", " leading"],
)
def test_register_rejects_invalid_domain(
    server_core: ServerCore, bad_domain: str
) -> None:
    with pytest.raises(ComponentError):
        server_core.register_component(RecordingComponent(domain=bad_domain))


def test_register_rejects_duplicate_domain(server_core: ServerCore) -> None:
    server_core.register_component(RecordingComponent(domain="metrics"))

    with pytest.raises(DuplicateComponentError) as exc_info:
        server_core.register_component(RecordingComponent(domain="metrics"))

    assert exc_info.value.domain == "metrics"
    assert "metrics" in str(exc_info.value)


def test_resolve_order_linear_chain(server_core: ServerCore) -> None:
    comp_c = RecordingComponent(domain="comp_c", dependencies=("comp_b",))
    comp_b = RecordingComponent(domain="comp_b", dependencies=("comp_a",))
    comp_a = RecordingComponent(domain="comp_a")
    for comp in (comp_c, comp_b, comp_a):
        server_core.register_component(comp)

    ordered = server_core.resolve_components()
    assert tuple(c.domain for c in ordered) == ("comp_a", "comp_b", "comp_c")


def test_resolve_order_diamond_dag_with_duplicate_dependencies(
    server_core: ServerCore,
) -> None:
    comp_a = RecordingComponent(domain="a")
    comp_b = RecordingComponent(domain="b", dependencies=("a",))
    comp_c = RecordingComponent(domain="c", dependencies=("a",))
    comp_d = RecordingComponent(domain="d", dependencies=("b", "c", "b"))
    for comp in (comp_d, comp_b, comp_c, comp_a):
        server_core.register_component(comp)

    ordered = server_core.resolve_components()
    assert tuple(c.domain for c in ordered) == ("a", "b", "c", "d")


def test_resolve_order_preserves_registration_order_on_tie_breaks(
    server_core: ServerCore,
) -> None:
    # Registered as [a, b, c] where b depends on a and c has no dependencies.
    # Once a completes, b (registration index 1) must still precede c (index 2).
    comp_a = RecordingComponent(domain="a")
    comp_b = RecordingComponent(domain="b", dependencies=("a",))
    comp_c = RecordingComponent(domain="c")
    for comp in (comp_a, comp_b, comp_c):
        server_core.register_component(comp)

    ordered = server_core.resolve_components()
    assert tuple(c.domain for c in ordered) == ("a", "b", "c")


def test_resolve_order_missing_dependency_raises(server_core: ServerCore) -> None:
    server_core.register_component(
        RecordingComponent(domain="mcp", dependencies=("search",))
    )

    with pytest.raises(MissingDependencyError) as exc_info:
        server_core.resolve_components()

    assert exc_info.value.domain == "mcp"
    assert exc_info.value.dependency == "search"
    assert "mcp" in str(exc_info.value)
    assert "search" in str(exc_info.value)


def test_resolve_order_self_cycle_raises_with_cycle_path(
    server_core: ServerCore,
) -> None:
    server_core.register_component(
        RecordingComponent(domain="self_dep", dependencies=("self_dep",))
    )

    with pytest.raises(DependencyCycleError) as exc_info:
        server_core.resolve_components()

    assert exc_info.value.cycle == ("self_dep", "self_dep")
    assert "self_dep -> self_dep" in str(exc_info.value)


def test_resolve_order_multi_node_cycle_raises_with_cycle_path(
    server_core: ServerCore,
) -> None:
    # 'outer' depends on 'a' (which is in cycle a -> b -> c -> a),
    # verifying 'outer' is excluded from the reported cycle tuple.
    server_core.register_component(
        RecordingComponent(domain="outer", dependencies=("a",))
    )
    server_core.register_component(RecordingComponent(domain="a", dependencies=("b",)))
    server_core.register_component(RecordingComponent(domain="b", dependencies=("c",)))
    server_core.register_component(RecordingComponent(domain="c", dependencies=("a",)))

    with pytest.raises(DependencyCycleError) as exc_info:
        server_core.resolve_components()

    cycle = exc_info.value.cycle
    assert cycle[0] == cycle[-1]
    assert set(cycle) == {"a", "b", "c"}
    assert "outer" not in cycle


def test_resolve_order_cycle_with_resolved_dependency_excludes_resolved_node(
    server_core: ServerCore,
) -> None:
    # 'base' is resolved by Kahn's pass before cycle extraction, so '_find_cycle'
    # skips 'base' when inspecting 'a's dependencies.
    server_core.register_component(RecordingComponent(domain="base"))
    server_core.register_component(
        RecordingComponent(domain="a", dependencies=("base", "b"))
    )
    server_core.register_component(RecordingComponent(domain="b", dependencies=("a",)))

    with pytest.raises(DependencyCycleError) as exc_info:
        server_core.resolve_components()

    cycle = exc_info.value.cycle
    assert cycle[0] == cycle[-1]
    assert set(cycle) == {"a", "b"}
    assert "base" not in cycle


async def test_lifecycle_setup_start_stop_order(server_core: ServerCore) -> None:
    events: list[tuple[str, str]] = []
    comp_b = RecordingComponent(domain="b", dependencies=("a",), events=events)
    comp_a = RecordingComponent(domain="a", events=events)
    comp_c = RecordingComponent(domain="c", dependencies=("b",), events=events)
    for comp in (comp_c, comp_b, comp_a):
        server_core.register_component(comp)

    await server_core.async_setup()
    await server_core.async_start()
    await server_core.async_stop()

    assert events == [
        ("setup", "a"),
        ("setup", "b"),
        ("setup", "c"),
        ("start", "a"),
        ("start", "b"),
        ("start", "c"),
        ("stop", "c"),
        ("stop", "b"),
        ("stop", "a"),
    ]
    assert all(core is server_core for core in comp_a.seen_cores)


async def test_async_stop_is_idempotent(server_core: ServerCore) -> None:
    events: list[tuple[str, str]] = []
    server_core.register_component(RecordingComponent(domain="webhooks", events=events))

    await server_core.async_setup()
    await server_core.async_start()
    await server_core.async_stop()
    await server_core.async_stop()

    assert events == [
        ("setup", "webhooks"),
        ("start", "webhooks"),
        ("stop", "webhooks"),
    ]


async def test_async_start_before_setup_raises(server_core: ServerCore) -> None:
    server_core.register_component(RecordingComponent(domain="webhooks"))

    with pytest.raises(ComponentError):
        await server_core.async_start()


async def test_async_setup_failure_rolls_back_setup_components_in_reverse(
    server_core: ServerCore,
) -> None:
    events: list[tuple[str, str]] = []
    comp_a = RecordingComponent(domain="a", events=events)
    comp_b = RecordingComponent(
        domain="b", dependencies=("a",), events=events, fail_stop=True
    )
    comp_c = RecordingComponent(
        domain="c", dependencies=("b",), events=events, fail_on="setup"
    )
    for comp in (comp_a, comp_b, comp_c):
        server_core.register_component(comp)

    with pytest.raises(RuntimeError, match="setup failure in c"):
        await server_core.async_setup()

    assert events == [
        ("setup", "a"),
        ("setup", "b"),
        ("stop", "b"),
        ("stop", "a"),
    ]


async def test_async_start_failure_rolls_back_failing_and_started_in_reverse(
    server_core: ServerCore,
) -> None:
    events: list[tuple[str, str]] = []
    comp_a = RecordingComponent(domain="a", events=events)
    comp_b = RecordingComponent(
        domain="b", dependencies=("a",), events=events, fail_stop=True
    )
    comp_c = RecordingComponent(
        domain="c", dependencies=("b",), events=events, fail_on="start"
    )
    for comp in (comp_a, comp_b, comp_c):
        server_core.register_component(comp)

    await server_core.async_setup()
    with pytest.raises(RuntimeError, match="start failure in c"):
        await server_core.async_start()

    # Subsequent stop is a no-op because rollback already stopped started components.
    await server_core.async_stop()

    assert events == [
        ("setup", "a"),
        ("setup", "b"),
        ("setup", "c"),
        ("start", "a"),
        ("start", "b"),
        ("stop", "c"),
        ("stop", "b"),
        ("stop", "a"),
    ]


async def test_async_stop_error_isolation(server_core: ServerCore) -> None:
    events: list[tuple[str, str]] = []
    comp_a = RecordingComponent(domain="a", events=events)
    comp_b = RecordingComponent(
        domain="b", dependencies=("a",), events=events, fail_stop=True
    )
    for comp in (comp_a, comp_b):
        server_core.register_component(comp)

    await server_core.async_setup()
    await server_core.async_start()
    await server_core.async_stop()

    assert events == [
        ("setup", "a"),
        ("setup", "b"),
        ("start", "a"),
        ("start", "b"),
        ("stop", "b"),
        ("stop", "a"),
    ]


async def test_empty_loader_lifecycle_is_noop(server_core: ServerCore) -> None:
    assert server_core.resolve_components() == ()
    await server_core.async_setup()
    await server_core.async_start()
    await server_core.async_stop()
