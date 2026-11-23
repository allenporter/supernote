"""Conformance and registry tests for built-in vertical server components."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import subprocess
import sys

import pytest

import supernote.server.components as components_pkg
from supernote.server.components import (
    BUILTIN_COMPONENTS,
    KNOWN_PLATFORMS,
    BuiltinComponentSpec,
    is_component_enabled,
    load_builtin_components,
    load_component_from_spec,
)
from supernote.server.components.ai import AiComponent
from supernote.server.components.http import jwt_auth_middleware
from supernote.server.core import (
    Component,
    ComponentError,
    ComponentLoader,
    PlatformHost,
    ServerCore,
)
from supernote.server.keys import HTTP_REGISTRAR_KEY
from supernote.server.trace import trace_middleware


def _discover_component_package_names() -> set[str]:
    """Return all public subpackage/module names under `supernote.server.components`."""
    return {
        mod_info.name
        for mod_info in pkgutil.iter_modules(components_pkg.__path__)
        if not mod_info.name.startswith("_")
    }


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


@pytest.mark.parametrize(
    "module_name",
    [
        "supernote.server.app",
        "supernote.server.core",
        "supernote.server.config",
        "supernote.server.metrics",
    ],
)
def test_core_modules_do_not_eagerly_import_component_subpackages(
    module_name: str,
) -> None:
    """Importing core server modules must not eagerly load any component subpackage."""
    check = (
        f"import sys, importlib; importlib.import_module({module_name!r}); "
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
        f"Component subpackages unexpectedly loaded when importing {module_name}: "
        f"{result.stdout.strip()}"
    )


@pytest.mark.parametrize(
    "spec",
    BUILTIN_COMPONENTS,
    ids=[spec.domain for spec in BUILTIN_COMPONENTS],
)
def test_component_imports_respect_declared_dependencies_and_platforms(
    spec: BuiltinComponentSpec,
) -> None:
    """Importing a component package and all its submodules must not pull in undeclared sibling components."""
    component = load_component_from_spec(spec)
    allowed = {spec.domain, *component.dependencies, *component.platforms}
    check = (
        f"import sys, importlib, pkgutil; "
        f"pkg = importlib.import_module('supernote.server.components.{spec.domain}'); "
        "[importlib.import_module(m.name) for m in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + '.')]; "
        "prefix = 'supernote.server.components.'; "
        "domains = sorted({"
        "m[len(prefix):].split('.', 1)[0] "
        "for m in sys.modules if m.startswith(prefix)"
        "}); "
        "print(','.join(domains))"
    )
    result = subprocess.run(
        [sys.executable, "-c", check],
        capture_output=True,
        text=True,
        check=True,
    )
    loaded_domains = {d for d in result.stdout.strip().split(",") if d}
    unexpected = loaded_domains - allowed
    assert not unexpected, (
        f"Component {spec.domain!r} imported undeclared sibling component(s): "
        f"{sorted(unexpected)} (allowed: {sorted(allowed)})"
    )


@pytest.mark.parametrize(
    "spec",
    [s for s in BUILTIN_COMPONENTS if s.domain != "http"],
    ids=[s.domain for s in BUILTIN_COMPONENTS if s.domain != "http"],
)
def test_non_http_component_modules_do_not_import_http_transport(
    spec: BuiltinComponentSpec,
) -> None:
    """Non-`http.py` modules in a component must remain isolated from main-port HTTP transport."""
    forbidden = (
        "aiohttp_asgi",
        "supernote.server.components.http",
        "supernote.server.routes.decorators",
    )
    check = (
        f"import importlib, pkgutil, sys; "
        f"pkg = importlib.import_module('supernote.server.components.{spec.domain}'); "
        "[importlib.import_module(m.name) for m in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + '.') if not m.name.endswith('.http')]; "
        f"hits = [f for f in {forbidden!r} if f in sys.modules or any(k.startswith(f + '.') for k in sys.modules)]; "
        "print(','.join(hits))"
    )
    result = subprocess.run(
        [sys.executable, "-c", check],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "", (
        f"Non-http modules in component {spec.domain!r} imported HTTP transport "
        f"module(s): {result.stdout.strip()}. Move HTTP routes/middlewares/ASGI mounts "
        f"into supernote/server/components/{spec.domain}/http.py."
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
def test_builtin_component_platforms_match_modules_1to1(
    spec: BuiltinComponentSpec,
) -> None:
    """Declared platforms must resolve to async setup functions, and platform files on disk must be declared."""
    component = load_component_from_spec(spec)
    pkg = importlib.import_module(f"supernote.server.components.{spec.domain}")

    for platform in component.platforms:
        platform_mod = importlib.import_module(f"{pkg.__name__}.{platform}")
        setup_fn = getattr(platform_mod, f"async_setup_{platform}", None)
        assert setup_fn is not None and inspect.iscoroutinefunction(setup_fn), (
            f"{platform_mod.__name__} must define async def async_setup_{platform}"
        )

    on_disk_platforms = {
        mod.name
        for mod in pkgutil.iter_modules(pkg.__path__)
        if mod.name in KNOWN_PLATFORMS
    }
    assert on_disk_platforms == (set(component.platforms) & KNOWN_PLATFORMS), (
        f"Component {spec.domain!r} platform files {on_disk_platforms} do not match "
        f"declared platforms {set(component.platforms)}"
    )


def _register_with_dependencies(
    loader: ComponentLoader,
    spec: BuiltinComponentSpec,
) -> None:
    """Register ``spec`` along with any transitive built-in dependencies."""
    specs_by_domain = {s.domain: s for s in BUILTIN_COMPONENTS}
    pending = [spec]
    while pending:
        current = pending.pop()
        if loader.get(current.domain) is not None:
            continue
        component = load_component_from_spec(current)
        loader.register(component)
        for dep in component.dependencies:
            if loader.get(dep) is None:
                pending.append(specs_by_domain[dep])


@pytest.mark.parametrize(
    "spec",
    BUILTIN_COMPONENTS,
    ids=[spec.domain for spec in BUILTIN_COMPONENTS],
)
async def test_component_full_lifecycle_and_idempotent_stop(
    spec: BuiltinComponentSpec,
    component_core: ServerCore,
) -> None:
    """Every component must support setup -> start -> stop -> stop cleanly."""
    loader = ComponentLoader()
    _register_with_dependencies(loader, spec)

    await loader.async_setup_all(component_core, {})
    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


@pytest.mark.parametrize(
    "spec",
    BUILTIN_COMPONENTS,
    ids=[spec.domain for spec in BUILTIN_COMPONENTS],
)
async def test_component_stop_after_setup_only(
    spec: BuiltinComponentSpec,
    component_core: ServerCore,
) -> None:
    """Every component must tear down cleanly if stopped after setup without starting."""
    loader = ComponentLoader()
    _register_with_dependencies(loader, spec)

    await loader.async_setup_all(component_core, {})
    await loader.async_stop_all(component_core)


async def test_all_builtin_components_http_platform_end_to_end(
    component_core: ServerCore,
) -> None:
    """All built-in components must set up, load the `http` platform, apply middlewares/routes, start, and stop cleanly together."""
    loader = ComponentLoader()
    for spec in BUILTIN_COMPONENTS:
        loader.register(load_component_from_spec(spec))

    await loader.async_setup_all(component_core, {})
    await loader.async_load_all_platforms(component_core)

    ai_comp = loader.get("ai")
    assert isinstance(ai_comp, AiComponent)
    ai_registrar = ai_comp.get_platform_registrar()
    assert {"apple", "fake", "gemini", "openai"} <= set(ai_registrar.ocr_providers)
    assert {"fake", "gemini", "openai"} <= set(ai_registrar.summary_providers)
    assert {"fake", "gemini", "openai"} <= set(ai_registrar.embedding_providers)

    http_registrar = component_core.app[HTTP_REGISTRAR_KEY]
    mcp_comp = loader.get("mcp")
    assert isinstance(mcp_comp, PlatformHost)
    mcp_registrar = mcp_comp.get_platform_registrar()
    assert set(mcp_registrar.tool_names) >= {
        "list_tasks",
        "create_task",
        "update_task",
        "delete_task",
    }

    middlewares = list(component_core.app.middlewares)
    trace_idx = middlewares.index(trace_middleware)
    assert trace_idx == len(http_registrar.outer_middlewares)
    assert middlewares[trace_idx + 1] is jwt_auth_middleware
    assert middlewares[trace_idx + 2 :] == list(http_registrar.inner_middlewares)

    resources = list(component_core.app.router.resources())
    canonicals = [r.canonical for r in resources]
    for expected_path in (
        "/",
        "/static",
        "/metrics",
        "/socket.io/",
        "/api/extended/ai/status",
        "/api/extended/events",
        "/api/extended/search",
        "/api/extended/transcript",
        "/api/schedule/feed.ics",
    ):
        assert expected_path in canonicals
    # Deferred public catch-all resources (e.g. MCP ASGIResource) must be mounted last.
    assert resources[-len(http_registrar.public_resources) :] == list(
        http_registrar.public_resources
    )

    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)


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
