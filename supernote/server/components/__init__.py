"""Built-in vertical server component registry and lazy loader.

Defines `BUILTIN_COMPONENTS`, the central declarative list of first-party
components under `supernote.server.components`, and `load_builtin_components`
to lazily import and register only enabled components.
"""

from __future__ import annotations

import importlib
import importlib.metadata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from supernote.server.core import Component, ComponentError, ComponentLoader

__all__ = [
    "BUILTIN_COMPONENTS",
    "KNOWN_PLATFORMS",
    "PLUGIN_ENTRY_POINT_GROUP",
    "BuiltinComponentSpec",
    "PluginEntryPoint",
    "is_component_enabled",
    "load_builtin_components",
    "load_component_from_spec",
    "load_external_plugins",
    "load_plugin_from_entry_point",
]

KNOWN_PLATFORMS: frozenset[str] = frozenset({"http", "mcp"})
PLUGIN_ENTRY_POINT_GROUP = "supernote.server_components"


@dataclass(frozen=True)
class BuiltinComponentSpec:
    """Declarative registration entry for a built-in vertical server component."""

    domain: str
    """Component domain and subpackage name under `supernote.server.components`."""
    import_path: str
    """Dotted `module:ClassName` path imported lazily only when enabled."""
    default_enabled: bool = False
    """Whether the component loads by default when `enabled` is not set in config."""


BUILTIN_COMPONENTS: tuple[BuiltinComponentSpec, ...] = (
    BuiltinComponentSpec(
        domain="http",
        import_path="supernote.server.components.http:HttpComponent",
        default_enabled=True,
    ),
    BuiltinComponentSpec(
        domain="mcp",
        import_path="supernote.server.components.mcp:McpComponent",
        default_enabled=True,
    ),
    BuiltinComponentSpec(
        domain="metrics",
        import_path="supernote.server.components.metrics:MetricsComponent",
        default_enabled=True,
    ),
    BuiltinComponentSpec(
        domain="oauth",
        import_path="supernote.server.components.oauth:OAuthComponent",
        default_enabled=True,
    ),
    BuiltinComponentSpec(
        domain="schedule",
        import_path="supernote.server.components.schedule:ScheduleComponent",
        default_enabled=True,
    ),
    BuiltinComponentSpec(
        domain="socketio",
        import_path="supernote.server.components.socketio:SocketIOComponent",
        default_enabled=True,
    ),
    BuiltinComponentSpec(
        domain="web_ui",
        import_path="supernote.server.components.web_ui:WebUiComponent",
        default_enabled=True,
    ),
    BuiltinComponentSpec(
        domain="webhooks",
        import_path="supernote.server.components.webhooks:WebhooksComponent",
        default_enabled=False,
    ),
)


def is_component_enabled(
    spec: BuiltinComponentSpec,
    component_config: Mapping[str, Any],
) -> bool:
    """Return whether ``spec`` should be loaded given its per-domain config dict."""
    if "enabled" in component_config:
        return bool(component_config["enabled"])
    return spec.default_enabled


def load_component_from_spec(spec: BuiltinComponentSpec) -> Component:
    """Lazily import and instantiate the `Component` named by ``spec.import_path``."""
    module_path, sep, attr_name = spec.import_path.partition(":")
    if not sep or not module_path or not attr_name:
        raise ComponentError(
            f"Invalid component import_path {spec.import_path!r}; expected 'module:ClassName'"
        )
    module = importlib.import_module(module_path)
    factory = getattr(module, attr_name)
    component = factory()
    if not isinstance(component, Component):
        raise ComponentError(
            f"Object {spec.import_path!r} did not return a Component instance"
        )
    if component.domain != spec.domain:
        raise ComponentError(
            f"Component {spec.import_path!r} reported domain {component.domain!r}, "
            f"expected {spec.domain!r}"
        )
    return component


def load_builtin_components(
    loader: ComponentLoader,
    component_configs: Mapping[str, Mapping[str, Any]],
    specs: Sequence[BuiltinComponentSpec] = BUILTIN_COMPONENTS,
) -> None:
    """Lazily import and register all enabled components from ``specs``."""
    for spec in specs:
        if not is_component_enabled(spec, component_configs.get(spec.domain, {})):
            continue
        loader.register(load_component_from_spec(spec))


class PluginEntryPoint(Protocol):
    """Structural contract matching `importlib.metadata.EntryPoint`."""

    @property
    def name(self) -> str: ...

    @property
    def value(self) -> str: ...

    def load(self) -> Any: ...


def load_plugin_from_entry_point(
    entry_point: PluginEntryPoint,
) -> Component:
    """Load and validate an external plugin `Component` from an entry point."""
    loaded = entry_point.load()
    if not isinstance(loaded, type) and isinstance(loaded, Component):
        component: Any = loaded
    elif callable(loaded):
        component = loaded()
    else:
        raise ComponentError(
            f"Entry point {entry_point.name!r} ({entry_point.value!r}) must resolve "
            "to a Component instance or zero-argument factory"
        )
    if not isinstance(component, Component):
        raise ComponentError(
            f"Entry point {entry_point.name!r} ({entry_point.value!r}) did not "
            "return a Component instance"
        )
    if component.domain != entry_point.name:
        raise ComponentError(
            f"Entry point {entry_point.name!r} reported domain {component.domain!r}, "
            f"expected {entry_point.name!r}"
        )
    return component


def load_external_plugins(
    loader: ComponentLoader,
    plugin_configs: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    group: str = PLUGIN_ENTRY_POINT_GROUP,
    entry_points: Sequence[PluginEntryPoint] | None = None,
) -> tuple[Component, ...]:
    """Discover, validate, and register external plugins via ``importlib.metadata``."""
    configs = plugin_configs or {}
    discovered: list[PluginEntryPoint] = (
        list(entry_points)
        if entry_points is not None
        else list(importlib.metadata.entry_points(group=group))
    )
    discovered.sort(key=lambda ep: (ep.name, ep.value))

    loaded_components: list[Component] = []
    for ep in discovered:
        ep_config = configs.get(ep.name, {})
        if "enabled" in ep_config and not bool(ep_config["enabled"]):
            continue
        component = load_plugin_from_entry_point(ep)
        loader.register(component)
        loaded_components.append(component)
    return tuple(loaded_components)
