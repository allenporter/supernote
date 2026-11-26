"""Conformance and registry tests for built-in vertical server components."""

from __future__ import annotations

import ast
import functools
import importlib
import inspect
import pkgutil
import subprocess
import sys
from collections import deque
from dataclasses import replace
from pathlib import Path

import pytest
from aiohttp import web

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
from supernote.server.components.http import (
    HTTP_REGISTRAR_KEY,
    HttpRegistrar,
    jwt_auth_middleware,
)
from supernote.server.core import (
    Component,
    ComponentError,
    ComponentLoader,
    PlatformHost,
    ServerCore,
)
from supernote.server.trace import trace_middleware

REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve_supernote_module_path(module_name: str) -> tuple[Path, bool] | None:
    """Resolve a ``supernote.*`` dotted module name to ``(file_path, is_package)``."""
    if module_name != "supernote" and not module_name.startswith("supernote."):
        return None
    rel = Path(*module_name.split("."))
    pkg_init = REPO_ROOT / rel / "__init__.py"
    if pkg_init.is_file():
        return pkg_init, True
    mod_file = (REPO_ROOT / rel).with_suffix(".py")
    if mod_file.is_file():
        return mod_file, False
    return None


def _is_type_checking_guard(test: ast.expr) -> bool:
    """Return True if an ``if`` condition is ``TYPE_CHECKING`` or ``typing.TYPE_CHECKING``."""
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


class _EagerImportVisitor(ast.NodeVisitor):
    """Collect module-level imports executed at import time (skipping defs and ``if TYPE_CHECKING``)."""

    def __init__(self, pkg_name: str) -> None:
        self._pkg_name = pkg_name
        self.imports: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking_guard(node.test):
            for stmt in node.orelse:
                self.visit(stmt)
        else:
            self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.add(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level > 0:
            pkg_parts = self._pkg_name.split(".") if self._pkg_name else []
            up = node.level - 1
            if up > len(pkg_parts):
                raise ValueError(
                    f"Relative import level {node.level} exceeds package depth for {self._pkg_name!r}"
                )
            base_parts = pkg_parts[: len(pkg_parts) - up] if up else pkg_parts
            base = ".".join(base_parts)
            target = f"{base}.{node.module}" if node.module else base
        else:
            target = node.module or ""
        if not target:
            return
        self.imports.add(target)
        for alias in node.names:
            if alias.name != "*":
                candidate = f"{target}.{alias.name}"
                if _resolve_supernote_module_path(candidate) is not None:
                    self.imports.add(candidate)


@functools.lru_cache(maxsize=None)
def _direct_eager_imports(module_name: str) -> frozenset[str]:
    """Parse ``module_name`` with AST and return its direct import-time dependencies."""
    resolved = _resolve_supernote_module_path(module_name)
    if resolved is None:
        return frozenset()
    file_path, is_pkg = resolved
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    pkg_name = module_name if is_pkg else module_name.rpartition(".")[0]
    visitor = _EagerImportVisitor(pkg_name)
    visitor.visit(tree)
    return frozenset(visitor.imports)


def _collect_eager_imports(seed_modules: list[str]) -> set[str]:
    """Return the transitive closure of static eager imports reachable from ``seed_modules``.

    Uses cached AST traversal instead of spawning a fresh Python subprocess per
    component so all component import-boundary checks run in milliseconds rather
    than ~2 cold interpreter startups per component. Dynamic runtime imports in
    ``supernote.server.app`` are covered separately by a single subprocess check.
    """
    visited: set[str] = set()
    queue: deque[str] = deque(seed_modules)
    while queue:
        mod = queue.popleft()
        if not mod or mod in visited:
            continue
        visited.add(mod)
        if mod == "supernote" or mod.startswith("supernote."):
            parent = mod.rpartition(".")[0]
            if parent and parent not in visited:
                queue.append(parent)
            for dep in _direct_eager_imports(mod):
                if dep not in visited:
                    queue.append(dep)
    return visited


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


def _discover_component_submodules(domain: str) -> list[str]:
    """Return all module names under ``supernote.server.components.<domain>`` without importing them."""
    pkg_name = f"supernote.server.components.{domain}"
    pkg_dir = REPO_ROOT / "supernote" / "server" / "components" / domain
    if not pkg_dir.is_dir():
        return [pkg_name]
    modules: list[str] = [pkg_name]
    for py_file in sorted(pkg_dir.rglob("*.py")):
        rel_parts = py_file.relative_to(pkg_dir).parts
        if any(part.startswith(".") or part == "__pycache__" for part in rel_parts):
            continue
        if py_file.name == "__init__.py":
            if len(rel_parts) > 1:
                modules.append(f"{pkg_name}.{'.'.join(rel_parts[:-1])}")
        else:
            mod_parts = (*rel_parts[:-1], py_file.stem)
            modules.append(f"{pkg_name}.{'.'.join(mod_parts)}")
    return modules


def test_importing_server_app_runtime_does_not_load_component_subpackages() -> None:
    """Verify in a clean subprocess that importing ``supernote.server.app`` triggers no dynamic component loads."""
    check = (
        "import sys, supernote.server.app; "
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
        "Component subpackages unexpectedly loaded at runtime when importing "
        f"supernote.server.app: {result.stdout.strip()}"
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
    imported = _collect_eager_imports([module_name])
    loaded = sorted(m for m in imported if m.startswith("supernote.server.components."))
    assert loaded == [], (
        f"Component subpackages unexpectedly loaded when importing {module_name}: "
        f"{','.join(loaded)}"
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
    imported = _collect_eager_imports(_discover_component_submodules(spec.domain))
    prefix = "supernote.server.components."
    loaded_domains = {
        m[len(prefix) :].split(".", 1)[0] for m in imported if m.startswith(prefix)
    }
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
    non_http_modules = [
        m
        for m in _discover_component_submodules(spec.domain)
        if not m.endswith(".http") and ".http." not in m
    ]
    imported = _collect_eager_imports(non_http_modules)
    hits = [
        f
        for f in forbidden
        if f in imported or any(k.startswith(f + ".") for k in imported)
    ]
    assert hits == [], (
        f"Non-http modules in component {spec.domain!r} imported HTTP transport "
        f"module(s): {','.join(hits)}. Move HTTP routes/middlewares/ASGI mounts "
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
    assert {"apple", "fake_ai", "gemini", "openai"} <= set(ai_registrar.ocr_providers)
    assert {"fake_ai", "gemini", "openai"} <= set(ai_registrar.summary_providers)
    assert {"fake_ai", "gemini", "openai"} <= set(ai_registrar.embedding_providers)

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
        "/api/extended/file/summary/list",
        "/api/extended/search",
        "/api/extended/system/components",
        "/api/extended/transcript",
        "/api/file/add/summary",
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

    # Re-running with enabled=False while IDLE unregisters the component
    load_builtin_components(
        loader, {"webhooks": {"enabled": False}}, specs=(default_on,)
    )
    assert loader.get("webhooks") is None


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


# Routes that the Web UI gates behind `isComponentRunning(domain)` / `isTabAvailable(...)`.
# Keep this map in sync with `supernote/server/static/js/` when moving routes between components.
UI_GATED_COMPONENT_ROUTES: dict[str, set[str]] = {
    "ai": {"/api/extended/ai/status"},
    "config": {
        "/api/extended/system/features",
        "/api/extended/system/components",
    },
    "conversion": {
        "/api/extended/file/note/cover",
        "/api/file/note/to/png",
    },
    "processor": {
        "/api/extended/file/note/metadata",
        "/api/extended/file/processing/status",
        "/api/extended/system/tasks",
        "/api/extended/system/tasks/retry",
    },
    "schedule": {
        "/api/file/schedule/task/all",
        "/api/file/schedule/group/all",
        "/api/schedule/feed.ics",
    },
    "search": {"/api/extended/search"},
    "summary": {
        "/api/extended/file/summary/list",
        "/api/file/query/summary",
        "/api/file/query/summary/group",
    },
    "transcript": {"/api/extended/transcript"},
    "wiki": {
        "/api/extended/wiki/pages",
        "/api/extended/wiki/status",
        "/api/extended/wiki/search",
    },
}


@pytest.mark.parametrize(
    ("domain", "expected_routes"),
    sorted(UI_GATED_COMPONENT_ROUTES.items()),
)
async def test_ui_gated_routes_owned_by_expected_components(
    component_core: ServerCore,
    domain: str,
    expected_routes: set[str],
) -> None:
    """Each route gated by `isComponentRunning(domain)` in the Web UI is registered by `domain`."""
    probe_app = web.Application()
    probe_core = replace(component_core, app=probe_app)
    registrar = HttpRegistrar(probe_app.router)

    http_mod = importlib.import_module(f"supernote.server.components.{domain}.http")
    await http_mod.async_setup_http(probe_core, registrar)

    registered = {r.canonical for r in probe_app.router.resources()}
    missing = expected_routes - registered
    assert not missing, (
        f"Component {domain!r} no longer registers UI-gated route(s) {sorted(missing)}; "
        "update the Web UI `isComponentRunning(...)` gate to the new owning component."
    )
