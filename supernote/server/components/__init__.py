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
    "KNOWN_PLATFORMS",
    "BuiltinComponentSpec",
    "is_component_enabled",
    "load_builtin_components",
    "load_component_from_spec",
]

KNOWN_PLATFORMS: frozenset[str] = frozenset(
    {"embedding", "http", "mcp", "ocr", "summary"}
)


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
        domain="ai",
        import_path="supernote.server.components.ai:AiComponent",
        default_enabled=True,
    ),
    BuiltinComponentSpec(
        domain="apple",
        import_path="supernote.server.components.apple:AppleComponent",
        default_enabled=False,
    ),
    BuiltinComponentSpec(
        domain="events",
        import_path="supernote.server.components.events:EventsComponent",
        default_enabled=True,
    ),
    BuiltinComponentSpec(
        domain="fake_ai",
        import_path="supernote.server.components.fake_ai:FakeAiComponent",
        default_enabled=False,
    ),
    BuiltinComponentSpec(
        domain="gemini",
        import_path="supernote.server.components.gemini:GeminiComponent",
        default_enabled=False,
    ),
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
        domain="openai",
        import_path="supernote.server.components.openai:OpenAIComponent",
        default_enabled=False,
    ),
    BuiltinComponentSpec(
        domain="schedule",
        import_path="supernote.server.components.schedule:ScheduleComponent",
        default_enabled=True,
    ),
    BuiltinComponentSpec(
        domain="search",
        import_path="supernote.server.components.search:SearchComponent",
        default_enabled=True,
    ),
    BuiltinComponentSpec(
        domain="socketio",
        import_path="supernote.server.components.socketio:SocketIOComponent",
        default_enabled=True,
    ),
    BuiltinComponentSpec(
        domain="transcript",
        import_path="supernote.server.components.transcript:TranscriptComponent",
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
