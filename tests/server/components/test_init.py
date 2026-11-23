"""Conformance and registry tests for built-in vertical server components."""

from __future__ import annotations

import pkgutil
import subprocess
import sys

import pytest
from aiohttp import web

import supernote.server.components as components_pkg
from supernote.server.components import (
    BUILTIN_COMPONENTS,
    BuiltinComponentSpec,
    is_component_enabled,
    load_builtin_components,
    load_component_from_spec,
)
from supernote.server.config import ServerConfig
from supernote.server.core import Component, ComponentError, ComponentLoader, ServerCore
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus
from supernote.server.services.blob import BlobStorage
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.file import FileService
from supernote.server.services.user import UserService


def _discover_component_package_names() -> set[str]:
    """Return all public subpackage/module names under `supernote.server.components`."""
    return {
        mod_info.name
        for mod_info in pkgutil.iter_modules(components_pkg.__path__)
        if not mod_info.name.startswith("_")
    }


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


def test_builtin_components_registry_matches_subpackages_1to1() -> None:
    """Every subpackage under `supernote/server/components/` must be linked in `BUILTIN_COMPONENTS`."""
    on_disk = _discover_component_package_names()
    registered = [spec.domain for spec in BUILTIN_COMPONENTS]

    assert len(registered) == len(set(registered)), (
        "Duplicate domains in BUILTIN_COMPONENTS"
    )
    assert set(registered) == on_disk, (
        f"BUILTIN_COMPONENTS domains {set(registered)} do not match "
        f"component packages on disk {on_disk}"
    )


def test_importing_app_does_not_eagerly_import_component_subpackages() -> None:
    """Importing `supernote.server.app` must not eagerly load any component subpackage."""
    check = (
        "import sys; import supernote.server.app; "
        "loaded = sorted("
        "m for m in sys.modules "
        "if m.startswith('supernote.server.components.')"
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
        f"Component subpackages unexpectedly loaded on app import: {result.stdout.strip()}"
    )


@pytest.mark.parametrize(
    "spec",
    BUILTIN_COMPONENTS,
    ids=[spec.domain for spec in BUILTIN_COMPONENTS],
)
def test_builtin_component_spec_links_to_valid_component(
    spec: BuiltinComponentSpec,
) -> None:
    """Every `BUILTIN_COMPONENTS` entry must resolve to a valid `Component` matching its domain."""
    assert spec.import_path.startswith(f"supernote.server.components.{spec.domain}:")
    component = load_component_from_spec(spec)
    assert isinstance(component, Component)
    assert component.domain == spec.domain

    loader = ComponentLoader()
    loader.register(component)
    assert loader.get(spec.domain) is component


def test_all_builtin_components_resolve_without_missing_deps_or_cycles() -> None:
    """All built-in components loaded together must form a valid acyclic DAG."""
    loader = ComponentLoader()
    for spec in BUILTIN_COMPONENTS:
        loader.register(load_component_from_spec(spec))

    ordered = loader.resolve_order()
    assert len(ordered) == len(BUILTIN_COMPONENTS)


@pytest.mark.parametrize(
    "spec",
    BUILTIN_COMPONENTS,
    ids=[spec.domain for spec in BUILTIN_COMPONENTS],
)
async def test_component_full_lifecycle_and_idempotent_stop(
    spec: BuiltinComponentSpec,
    conformance_core: ServerCore,
) -> None:
    """Every component must support setup -> start -> stop -> stop cleanly."""
    loader = ComponentLoader()
    loader.register(load_component_from_spec(spec))

    await loader.async_setup_all(conformance_core, {})
    await loader.async_start_all(conformance_core)
    await loader.async_stop_all(conformance_core)
    await loader.async_stop_all(conformance_core)


@pytest.mark.parametrize(
    "spec",
    BUILTIN_COMPONENTS,
    ids=[spec.domain for spec in BUILTIN_COMPONENTS],
)
async def test_component_stop_after_setup_only(
    spec: BuiltinComponentSpec,
    conformance_core: ServerCore,
) -> None:
    """Every component must tear down cleanly if stopped after setup without starting."""
    loader = ComponentLoader()
    loader.register(load_component_from_spec(spec))

    await loader.async_setup_all(conformance_core, {})
    await loader.async_stop_all(conformance_core)


def test_is_component_enabled_respects_default_and_config_override() -> None:
    opt_in = BuiltinComponentSpec(
        domain="webhooks",
        import_path="supernote.server.components.webhooks:WebhooksComponent",
        default_enabled=False,
    )
    opt_out = BuiltinComponentSpec(
        domain="webhooks",
        import_path="supernote.server.components.webhooks:WebhooksComponent",
        default_enabled=True,
    )

    assert is_component_enabled(opt_in, {}) is False
    assert is_component_enabled(opt_in, {"enabled": True}) is True
    assert is_component_enabled(opt_out, {}) is True
    assert is_component_enabled(opt_out, {"enabled": False}) is False


def test_load_builtin_components_loads_only_enabled_specs() -> None:
    default_on = BuiltinComponentSpec(
        domain="webhooks",
        import_path="supernote.server.components.webhooks:WebhooksComponent",
        default_enabled=True,
    )
    loader = ComponentLoader()
    load_builtin_components(
        loader, {"webhooks": {"enabled": False}}, specs=(default_on,)
    )
    assert loader.components == ()

    load_builtin_components(loader, {}, specs=(default_on,))
    assert loader.get("webhooks") is not None


@pytest.mark.parametrize(
    "bad_import_path",
    ["no_colon", ":MissingModule", "missing_attr:"],
)
def test_load_component_from_spec_rejects_malformed_import_path(
    bad_import_path: str,
) -> None:
    spec = BuiltinComponentSpec(domain="bad", import_path=bad_import_path)
    with pytest.raises(ComponentError, match="Invalid component import_path"):
        load_component_from_spec(spec)


def test_load_component_from_spec_rejects_non_component_object() -> None:
    spec = BuiltinComponentSpec(domain="not_comp", import_path="builtins:dict")
    with pytest.raises(ComponentError, match="did not return a Component instance"):
        load_component_from_spec(spec)


def test_load_component_from_spec_rejects_domain_mismatch() -> None:
    spec = BuiltinComponentSpec(
        domain="wrong_domain",
        import_path="supernote.server.components.webhooks:WebhooksComponent",
    )
    with pytest.raises(ComponentError, match="expected 'wrong_domain'"):
        load_component_from_spec(spec)
