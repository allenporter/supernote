"""Unit tests for `supernote.server.core` (`ServerCore`, `Component`, `ComponentLoader`)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, dataclass, field
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web

from supernote.server.config import ServerConfig
from supernote.server.core import (
    Component,
    ComponentError,
    ComponentLoader,
    DependencyCycleError,
    DuplicateComponentError,
    MissingDependencyError,
    PlatformHost,
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
    platforms: tuple[str, ...] = ()
    events: list[tuple[str, str]] = field(default_factory=list)
    seen_cores: list[ServerCore] = field(default_factory=list)
    seen_configs: list[Mapping[str, Any]] = field(default_factory=list)
    fail_on: str | None = None
    cancel_on: str | None = None
    fail_stop: bool = False

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        self.seen_cores.append(core)
        self.seen_configs.append(config)
        if self.cancel_on == "setup":
            raise asyncio.CancelledError
        if self.fail_on == "setup":
            raise RuntimeError(f"setup failure in {self.domain}")
        self.events.append(("setup", self.domain))

    async def async_start(self, core: ServerCore) -> None:
        self.seen_cores.append(core)
        if self.cancel_on == "start":
            raise asyncio.CancelledError
        if self.fail_on == "start":
            raise RuntimeError(f"start failure in {self.domain}")
        self.events.append(("start", self.domain))

    async def async_stop(self, core: ServerCore) -> None:
        self.seen_cores.append(core)
        self.events.append(("stop", self.domain))
        if self.fail_stop:
            raise RuntimeError(f"stop failure in {self.domain}")


@pytest.fixture
def loader() -> ComponentLoader:
    """Return a fresh `ComponentLoader` instance."""
    return ComponentLoader()


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


def test_server_core_is_immutable(server_core: ServerCore) -> None:
    core_as_any: Any = server_core
    with pytest.raises(FrozenInstanceError):
        core_as_any.config = None


async def test_loader_iter_platform_components_preserves_topological_order(
    loader: ComponentLoader,
    server_core: ServerCore,
) -> None:
    comp_b = RecordingComponent(domain="b", dependencies=("a",), platforms=("http",))
    comp_a = RecordingComponent(domain="a", platforms=("http",))
    comp_c = RecordingComponent(domain="c", platforms=())
    for comp in (comp_b, comp_c, comp_a):
        loader.register(comp)

    await loader.async_setup_all(server_core, {})
    assert loader.iter_platform_components("http") == (comp_a, comp_b)
    assert loader.iter_platform_components("metrics") == ()


async def test_loader_async_load_platform_invokes_setup_and_validates_entry(
    loader: ComponentLoader,
    server_core: ServerCore,
) -> None:
    from supernote.server.components.http import HttpRegistrar  # noqa: PLC0415
    from supernote.server.components.socketio import (  # noqa: PLC0415
        SocketIOComponent,
    )

    loader.register(SocketIOComponent())
    await loader.async_setup_all(server_core, {})

    registrar = HttpRegistrar()
    await loader.async_load_platform("http", server_core, registrar)
    assert registrar.public_prefixes == ("/socket.io",)


async def test_loader_async_load_platform_missing_setup_fn_raises(
    loader: ComponentLoader,
    server_core: ServerCore,
) -> None:
    from supernote.server.components.socketio import (  # noqa: PLC0415
        SocketIOComponent,
    )

    class BadPlatformComponent(SocketIOComponent):
        __module__ = SocketIOComponent.__module__
        platforms = ("manager",)

    loader.register(BadPlatformComponent())
    await loader.async_setup_all(server_core, {})

    with pytest.raises(ComponentError, match="must define 'async_setup_manager'"):
        await loader.async_load_platform("manager", server_core, object())


async def test_loader_async_load_platform_before_setup_raises(
    loader: ComponentLoader,
    server_core: ServerCore,
) -> None:
    loader.register(RecordingComponent(domain="a", platforms=("http",)))

    with pytest.raises(ComponentError, match="Cannot load platform 'http'"):
        await loader.async_load_platform("http", server_core, object())


def test_loader_register_and_accessors(loader: ComponentLoader) -> None:
    comp = RecordingComponent(domain="webhooks")
    assert isinstance(comp, Component)

    loader.register(comp)

    assert loader.get("webhooks") is comp
    assert loader.get("missing") is None
    assert loader.components == (comp,)


@pytest.mark.parametrize(
    "bad_domain",
    ["", "   ", "UpperCase", "1leading_digit", "bad-hyphen", "bad/slash", " leading"],
)
def test_register_rejects_invalid_domain(
    loader: ComponentLoader, bad_domain: str
) -> None:
    with pytest.raises(ComponentError):
        loader.register(RecordingComponent(domain=bad_domain))


def test_register_rejects_duplicate_domain(loader: ComponentLoader) -> None:
    loader.register(RecordingComponent(domain="metrics"))

    with pytest.raises(DuplicateComponentError) as exc_info:
        loader.register(RecordingComponent(domain="metrics"))

    assert exc_info.value.domain == "metrics"
    assert "metrics" in str(exc_info.value)


async def test_register_after_setup_raises(
    loader: ComponentLoader, server_core: ServerCore
) -> None:
    loader.register(RecordingComponent(domain="a"))
    await loader.async_setup_all(server_core, {})

    with pytest.raises(ComponentError, match="Cannot register component after setup"):
        loader.register(RecordingComponent(domain="b"))


def test_resolve_order_linear_chain(loader: ComponentLoader) -> None:
    comp_c = RecordingComponent(domain="comp_c", dependencies=("comp_b",))
    comp_b = RecordingComponent(domain="comp_b", dependencies=("comp_a",))
    comp_a = RecordingComponent(domain="comp_a")
    for comp in (comp_c, comp_b, comp_a):
        loader.register(comp)

    ordered = loader.resolve_order()
    assert tuple(c.domain for c in ordered) == ("comp_a", "comp_b", "comp_c")


def test_resolve_order_diamond_dag_with_duplicate_dependencies(
    loader: ComponentLoader,
) -> None:
    comp_a = RecordingComponent(domain="a")
    comp_b = RecordingComponent(domain="b", dependencies=("a",))
    comp_c = RecordingComponent(domain="c", dependencies=("a",))
    comp_d = RecordingComponent(domain="d", dependencies=("b", "c", "b"))
    for comp in (comp_d, comp_b, comp_c, comp_a):
        loader.register(comp)

    ordered = loader.resolve_order()
    assert tuple(c.domain for c in ordered) == ("a", "b", "c", "d")


def test_resolve_order_preserves_registration_order_on_tie_breaks(
    loader: ComponentLoader,
) -> None:
    # Registered as [a, b, c] where b depends on a and c has no dependencies.
    # Once a completes, b (registration index 1) must still precede c (index 2).
    comp_a = RecordingComponent(domain="a")
    comp_b = RecordingComponent(domain="b", dependencies=("a",))
    comp_c = RecordingComponent(domain="c")
    for comp in (comp_a, comp_b, comp_c):
        loader.register(comp)

    ordered = loader.resolve_order()
    assert tuple(c.domain for c in ordered) == ("a", "b", "c")


def test_resolve_order_missing_dependency_raises(loader: ComponentLoader) -> None:
    loader.register(RecordingComponent(domain="mcp", dependencies=("search",)))

    with pytest.raises(MissingDependencyError) as exc_info:
        loader.resolve_order()

    assert exc_info.value.domain == "mcp"
    assert exc_info.value.dependency == "search"
    assert "mcp" in str(exc_info.value)
    assert "search" in str(exc_info.value)


def test_resolve_order_self_cycle_raises_with_cycle_path(
    loader: ComponentLoader,
) -> None:
    loader.register(RecordingComponent(domain="self_dep", dependencies=("self_dep",)))

    with pytest.raises(DependencyCycleError) as exc_info:
        loader.resolve_order()

    assert exc_info.value.cycle == ("self_dep", "self_dep")
    assert "self_dep -> self_dep" in str(exc_info.value)


def test_resolve_order_multi_node_cycle_raises_with_cycle_path(
    loader: ComponentLoader,
) -> None:
    # 'outer' depends on 'a' (which is in cycle a -> b -> c -> a),
    # verifying 'outer' is excluded from the reported cycle tuple.
    loader.register(RecordingComponent(domain="outer", dependencies=("a",)))
    loader.register(RecordingComponent(domain="a", dependencies=("b",)))
    loader.register(RecordingComponent(domain="b", dependencies=("c",)))
    loader.register(RecordingComponent(domain="c", dependencies=("a",)))

    with pytest.raises(DependencyCycleError) as exc_info:
        loader.resolve_order()

    cycle = exc_info.value.cycle
    assert cycle[0] == cycle[-1]
    assert set(cycle) == {"a", "b", "c"}
    assert "outer" not in cycle


def test_resolve_order_cycle_with_resolved_dependency_excludes_resolved_node(
    loader: ComponentLoader,
) -> None:
    loader.register(RecordingComponent(domain="base"))
    loader.register(RecordingComponent(domain="a", dependencies=("base", "b")))
    loader.register(RecordingComponent(domain="b", dependencies=("a",)))

    with pytest.raises(DependencyCycleError) as exc_info:
        loader.resolve_order()

    cycle = exc_info.value.cycle
    assert cycle[0] == cycle[-1]
    assert set(cycle) == {"a", "b"}
    assert "base" not in cycle


async def test_lifecycle_setup_start_stop_order(
    loader: ComponentLoader, server_core: ServerCore
) -> None:
    events: list[tuple[str, str]] = []
    comp_b = RecordingComponent(domain="b", dependencies=("a",), events=events)
    comp_a = RecordingComponent(domain="a", events=events)
    comp_c = RecordingComponent(domain="c", dependencies=("b",), events=events)
    for comp in (comp_c, comp_b, comp_a):
        loader.register(comp)

    await loader.async_setup_all(server_core, {"a": {"enabled": True}})
    await loader.async_start_all(server_core)
    await loader.async_stop_all(server_core)

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
    assert comp_a.seen_configs == [{"enabled": True}]
    assert comp_b.seen_configs == [{}]
    assert comp_c.seen_configs == [{}]


async def test_async_stop_is_idempotent(
    loader: ComponentLoader, server_core: ServerCore
) -> None:
    events: list[tuple[str, str]] = []
    loader.register(RecordingComponent(domain="webhooks", events=events))

    await loader.async_setup_all(server_core, {})
    await loader.async_start_all(server_core)
    await loader.async_stop_all(server_core)
    await loader.async_stop_all(server_core)

    assert events == [
        ("setup", "webhooks"),
        ("start", "webhooks"),
        ("stop", "webhooks"),
    ]


async def test_async_stop_after_setup_only_stops_initialized_components(
    loader: ComponentLoader, server_core: ServerCore
) -> None:
    events: list[tuple[str, str]] = []
    loader.register(RecordingComponent(domain="a", events=events))
    loader.register(RecordingComponent(domain="b", dependencies=("a",), events=events))

    await loader.async_setup_all(server_core, {})
    await loader.async_stop_all(server_core)

    assert events == [
        ("setup", "a"),
        ("setup", "b"),
        ("stop", "b"),
        ("stop", "a"),
    ]


async def test_async_start_before_setup_raises(
    loader: ComponentLoader, server_core: ServerCore
) -> None:
    loader.register(RecordingComponent(domain="webhooks"))

    with pytest.raises(ComponentError):
        await loader.async_start_all(server_core)


async def test_double_setup_raises(
    loader: ComponentLoader, server_core: ServerCore
) -> None:
    loader.register(RecordingComponent(domain="webhooks"))
    await loader.async_setup_all(server_core, {})

    with pytest.raises(ComponentError, match="Cannot run async_setup_all"):
        await loader.async_setup_all(server_core, {})


async def test_double_start_raises(
    loader: ComponentLoader, server_core: ServerCore
) -> None:
    loader.register(RecordingComponent(domain="webhooks"))
    await loader.async_setup_all(server_core, {})
    await loader.async_start_all(server_core)

    with pytest.raises(ComponentError):
        await loader.async_start_all(server_core)


async def test_async_setup_failure_rolls_back_setup_components_in_reverse(
    loader: ComponentLoader, server_core: ServerCore
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
        loader.register(comp)

    with pytest.raises(RuntimeError, match="setup failure in c"):
        await loader.async_setup_all(server_core, {})

    assert events == [
        ("setup", "a"),
        ("setup", "b"),
        ("stop", "b"),
        ("stop", "a"),
    ]


async def test_async_setup_cancelled_rolls_back_and_reraises(
    loader: ComponentLoader, server_core: ServerCore
) -> None:
    events: list[tuple[str, str]] = []
    loader.register(RecordingComponent(domain="a", events=events))
    loader.register(
        RecordingComponent(
            domain="b", dependencies=("a",), events=events, cancel_on="setup"
        )
    )

    with pytest.raises(asyncio.CancelledError):
        await loader.async_setup_all(server_core, {})

    assert events == [("setup", "a"), ("stop", "a")]


async def test_async_start_failure_rolls_back_all_initialized_in_reverse(
    loader: ComponentLoader, server_core: ServerCore
) -> None:
    events: list[tuple[str, str]] = []
    comp_a = RecordingComponent(domain="a", events=events)
    comp_b = RecordingComponent(
        domain="b", dependencies=("a",), events=events, fail_stop=True
    )
    comp_c = RecordingComponent(
        domain="c", dependencies=("b",), events=events, fail_on="start"
    )
    comp_d = RecordingComponent(domain="d", dependencies=("c",), events=events)
    for comp in (comp_a, comp_b, comp_c, comp_d):
        loader.register(comp)

    await loader.async_setup_all(server_core, {})
    with pytest.raises(RuntimeError, match="start failure in c"):
        await loader.async_start_all(server_core)

    # Subsequent stop is a no-op because rollback already stopped all initialized components.
    await loader.async_stop_all(server_core)

    assert events == [
        ("setup", "a"),
        ("setup", "b"),
        ("setup", "c"),
        ("setup", "d"),
        ("start", "a"),
        ("start", "b"),
        ("stop", "d"),
        ("stop", "c"),
        ("stop", "b"),
        ("stop", "a"),
    ]


async def test_async_start_cancelled_rolls_back_and_reraises(
    loader: ComponentLoader, server_core: ServerCore
) -> None:
    events: list[tuple[str, str]] = []
    loader.register(RecordingComponent(domain="a", events=events))
    loader.register(
        RecordingComponent(
            domain="b", dependencies=("a",), events=events, cancel_on="start"
        )
    )

    await loader.async_setup_all(server_core, {})
    with pytest.raises(asyncio.CancelledError):
        await loader.async_start_all(server_core)

    assert events == [
        ("setup", "a"),
        ("setup", "b"),
        ("start", "a"),
        ("stop", "b"),
        ("stop", "a"),
    ]


async def test_async_stop_error_isolation(
    loader: ComponentLoader, server_core: ServerCore
) -> None:
    events: list[tuple[str, str]] = []
    comp_a = RecordingComponent(domain="a", events=events)
    comp_b = RecordingComponent(
        domain="b", dependencies=("a",), events=events, fail_stop=True
    )
    for comp in (comp_a, comp_b):
        loader.register(comp)

    await loader.async_setup_all(server_core, {})
    await loader.async_start_all(server_core)
    await loader.async_stop_all(server_core)

    assert events == [
        ("setup", "a"),
        ("setup", "b"),
        ("start", "a"),
        ("start", "b"),
        ("stop", "b"),
        ("stop", "a"),
    ]


async def test_empty_loader_lifecycle_is_noop(
    loader: ComponentLoader, server_core: ServerCore
) -> None:
    assert loader.resolve_order() == ()
    await loader.async_setup_all(server_core, {})
    await loader.async_start_all(server_core)
    await loader.async_stop_all(server_core)


async def test_async_load_all_platforms_requires_setup_state(
    loader: ComponentLoader, server_core: ServerCore
) -> None:
    with pytest.raises(ComponentError, match="Cannot load platforms in state"):
        await loader.async_load_all_platforms(server_core)


async def test_async_load_all_platforms_loads_finalizes_and_rolls_back_on_error(
    loader: ComponentLoader, server_core: ServerCore
) -> None:
    events: list[tuple[str, str]] = []

    class _RecordingHost(RecordingComponent):
        hosted_platforms: tuple[str, ...] = ("custom_plat",)

        def __init__(self, *, fail_finalize: bool = False) -> None:
            super().__init__(domain="host", events=events)
            self._fail_finalize = fail_finalize
            self.registrar: list[str] = []

        def get_platform_registrar(self) -> list[str]:
            return self.registrar

        async def async_finalize_platforms(self, core: ServerCore) -> None:
            events.append(("finalize", self.domain))
            if self._fail_finalize:
                raise RuntimeError("finalize boom")

    host = _RecordingHost()
    assert isinstance(host, PlatformHost)
    loader.register(host)
    loader.register(RecordingComponent(domain="plain", events=events))

    await loader.async_setup_all(server_core, {})
    await loader.async_load_all_platforms(server_core)
    assert ("finalize", "host") in events

    failing_events: list[tuple[str, str]] = []
    failing_loader = ComponentLoader()
    failing_host = _RecordingHost(fail_finalize=True)
    failing_host.events = failing_events
    failing_loader.register(failing_host)
    await failing_loader.async_setup_all(server_core, {})
    with pytest.raises(RuntimeError, match="finalize boom"):
        await failing_loader.async_load_all_platforms(server_core)
    assert ("stop", "host") in failing_events
