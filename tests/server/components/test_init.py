"""Conformance tests for built-in vertical server components under `supernote/server/components/`."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import subprocess
import sys
from collections.abc import Callable

import pytest
from aiohttp import web

import supernote.server.components as components_pkg
from supernote.server.config import ServerConfig
from supernote.server.core import Component, ComponentLoader, ServerCore
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus
from supernote.server.services.blob import BlobStorage
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.file import FileService
from supernote.server.services.user import UserService


def _discover_builtin_component_factories() -> list[
    tuple[str, Callable[[], Component]]
]:
    """Discover all built-in component packages and their zero-arg `Component` classes."""
    discovered: list[tuple[str, Callable[[], Component]]] = []
    for mod_info in sorted(
        pkgutil.iter_modules(components_pkg.__path__), key=lambda m: m.name
    ):
        if mod_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{components_pkg.__name__}.{mod_info.name}")
        factories = [
            obj
            for _, obj in inspect.getmembers(module, inspect.isclass)
            if obj.__module__ == module.__name__ and hasattr(obj, "async_setup")
        ]
        assert len(factories) == 1, (
            f"Component package {module.__name__!r} must define exactly one Component "
            f"class, found {len(factories)}"
        )
        discovered.append((mod_info.name, factories[0]))
    return discovered


BUILTIN_COMPONENT_FACTORIES = _discover_builtin_component_factories()


@pytest.fixture
def conformance_core(
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    blob_storage: BlobStorage,
    user_service: UserService,
    file_service: FileService,
) -> ServerCore:
    """Create a `ServerCore` backed by shared test fixtures for component conformance."""
    return ServerCore(
        config=server_config,
        app=web.Application(),
        event_bus=LocalEventBus(),
        session_manager=session_manager,
        coordination=coordination_service,
        blob_storage=blob_storage,
        user_service=user_service,
        file_service=file_service,
    )


def test_builtin_components_discovered() -> None:
    """Ensure at least one built-in vertical component is discovered."""
    assert len(BUILTIN_COMPONENT_FACTORIES) >= 1


def test_importing_app_does_not_eagerly_import_components() -> None:
    """Importing `supernote.server.app` must not eagerly load optional components."""
    check = (
        "import sys; import supernote.server.app; "
        "loaded = sorted("
        "m for m in sys.modules "
        "if m == 'supernote.server.components' "
        "or m.startswith('supernote.server.components.')"
        "); "
        "print(','.join(loaded))"
    )
    result = subprocess.run(
        [sys.executable, "-c", check],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "", (
        f"Component modules unexpectedly loaded on app import: {result.stdout.strip()}"
    )


@pytest.mark.parametrize(
    ("pkg_name", "factory"),
    BUILTIN_COMPONENT_FACTORIES,
    ids=[name for name, _ in BUILTIN_COMPONENT_FACTORIES],
)
def test_component_implements_protocol_and_matches_package_domain(
    pkg_name: str,
    factory: Callable[[], Component],
) -> None:
    """Every component must satisfy the `Component` protocol and match its package name."""
    component = factory()
    assert isinstance(component, Component)
    assert component.domain == pkg_name

    loader = ComponentLoader()
    loader.register(component)
    assert loader.get(pkg_name) is component


def test_all_builtin_components_resolve_without_missing_deps_or_cycles() -> None:
    """All built-in components registered together must form a valid acyclic DAG."""
    loader = ComponentLoader()
    for _, factory in BUILTIN_COMPONENT_FACTORIES:
        loader.register(factory())

    ordered = loader.resolve_order()
    assert len(ordered) == len(BUILTIN_COMPONENT_FACTORIES)


@pytest.mark.parametrize(
    ("pkg_name", "factory"),
    BUILTIN_COMPONENT_FACTORIES,
    ids=[name for name, _ in BUILTIN_COMPONENT_FACTORIES],
)
async def test_component_full_lifecycle_and_idempotent_stop(
    pkg_name: str,
    factory: Callable[[], Component],
    conformance_core: ServerCore,
) -> None:
    """Every component must support setup -> start -> stop -> stop cleanly."""
    loader = ComponentLoader()
    loader.register(factory())

    await loader.async_setup_all(conformance_core)
    await loader.async_start_all(conformance_core)
    await loader.async_stop_all(conformance_core)
    await loader.async_stop_all(conformance_core)


@pytest.mark.parametrize(
    ("pkg_name", "factory"),
    BUILTIN_COMPONENT_FACTORIES,
    ids=[name for name, _ in BUILTIN_COMPONENT_FACTORIES],
)
async def test_component_stop_after_setup_only(
    pkg_name: str,
    factory: Callable[[], Component],
    conformance_core: ServerCore,
) -> None:
    """Every component must tear down cleanly if stopped after setup without starting."""
    loader = ComponentLoader()
    loader.register(factory())

    await loader.async_setup_all(conformance_core)
    await loader.async_stop_all(conformance_core)
