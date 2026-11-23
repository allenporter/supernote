"""Built-in vertical server component registry and lazy loader.

Defines `BUILTIN_COMPONENTS`, the central declarative list of first-party
components under `supernote.server.components`, and `load_builtin_components`
to lazily import and register only enabled components.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from supernote.server.core import Component, ComponentError, ComponentLoader

__all__ = [
    "BUILTIN_COMPONENTS",
    "BuiltinComponentSpec",
    "is_component_enabled",
    "load_builtin_components",
    "load_component_from_spec",
]


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
        domain="socketio",
        import_path="supernote.server.components.socketio:SocketIOComponent",
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
