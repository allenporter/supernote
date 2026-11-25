"""Configuration resolution service for built-in vertical server components.

Resolves effective per-component configuration across four priority tiers
(`env` > `yaml` > `database` > `default`) and persists dynamic overrides in
`CoordinationService`.
"""

from __future__ import annotations

import copy
import importlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from typing import TYPE_CHECKING, Any

from aiohttp import web
from mashumaro.exceptions import InvalidFieldValue, MissingField
from mashumaro.mixins.dict import DataClassDictMixin

from supernote.server.components import (
    BUILTIN_COMPONENTS,
    BuiltinComponentSpec,
    is_component_enabled,
)
from supernote.server.config import ComponentConfigSource, ServerConfig
from supernote.server.core import ComponentError, ComponentLoader

if TYPE_CHECKING:
    from supernote.server.services.coordination import CoordinationService

logger = logging.getLogger(__name__)

_COMPONENT_CONFIG_KEY_PREFIX = "component_config:"
_AI_PROVIDER_DOMAINS: frozenset[str] = frozenset(
    {"apple", "fake_ai", "gemini", "openai"}
)


def _configured_ai_provider_domains(server_config: ServerConfig) -> set[str]:
    return server_config.ai.active_provider_types & _AI_PROVIDER_DOMAINS


def _resolve_static_component_sources(
    server_config: ServerConfig,
) -> dict[str, ComponentConfigSource]:
    """Return the static source tier (`ENV` or `YAML`) for every explicitly configured component domain.

    Starts from the per-field sources recorded by `ServerConfig.load` and expands
    an explicit `ai:` section in `config.yaml` to the active AI provider component
    domains (`apple`, `fake_ai`, `gemini`, `openai`).
    """
    sources = dict(server_config.component_sources)
    if "ai" in sources:
        for domain in _configured_ai_provider_domains(server_config):
            sources.setdefault(domain, sources["ai"])
    return sources


def build_static_component_configs(
    server_config: ServerConfig,
) -> dict[str, dict[str, Any]]:
    """Build a per-component configuration dictionary (`{domain: {key: value}}`) from `ServerConfig`.

    This is a transitional bridge from legacy top-level `config.yaml` fields
    (such as `mcp_enabled: true`, `web_enabled: true`, or `ai.providers`) to
    the target format where every component is configured under its own
    root-level `<domain>:` section in `config.yaml` (e.g. `mcp: {enabled: true}`).

    The dictionary returned here (`{domain: config_dict}`) is the target end-state
    shape consumed by `ComponentLoader` and `ConfigService`.

    TODO: Once all configurable components define a `config_schema_path` dataclass
    and read from their `async_setup(core, config)` mapping rather than flat
    `core.config` attributes, retire the legacy `metadata={"component": ...}`
    and `_AI_PROVIDER_DOMAINS` bridging below.
    """
    ai_domains = _configured_ai_provider_domains(server_config)
    configs: dict[str, dict[str, Any]] = {
        domain: copy.deepcopy(cfg)
        for domain, cfg in server_config.root_component_configs.items()
    }
    for domain in _AI_PROVIDER_DOMAINS:
        configs[domain] = {
            **configs.get(domain, {}),
            "enabled": domain in ai_domains,
        }
    for f in fields(server_config):
        comp_meta = f.metadata.get("component")
        val = getattr(server_config, f.name)
        if isinstance(comp_meta, str):
            if val or comp_meta in configs:
                configs[comp_meta] = {
                    **configs.get(comp_meta, {}),
                    **copy.deepcopy(val),
                }
            else:
                configs[comp_meta] = {}
        elif isinstance(comp_meta, tuple):
            domain, target_key = comp_meta
            configs[domain] = {
                **configs.get(domain, {}),
                target_key: copy.deepcopy(val),
            }
    # Legacy one-off: `oauth` is historically toggled alongside `mcp_enabled`
    # rather than having its own flag.
    # TODO: Support `oauth` enabled by default independently of `mcp`.
    configs["oauth"] = {
        **configs.get("oauth", {}),
        "enabled": bool(configs.get("mcp", {}).get("enabled", True)),
    }
    return configs


@dataclass(frozen=True)
class ResolvedComponentConfig:
    """Resolved configuration dictionary, enabled status, and winning source tier for a component."""

    domain: str
    """Component domain identifier."""
    config: dict[str, Any]
    """Effective configuration dictionary passed to `Component.async_setup`."""
    enabled: bool
    """Whether the component is enabled after resolving all priority tiers."""
    source: ComponentConfigSource
    """Winning configuration tier (`ENV`, `YAML`, `DATABASE`, or `DEFAULT`)."""


def load_component_config_schema(
    spec: BuiltinComponentSpec,
) -> type[DataClassDictMixin] | None:
    """Lazily import and return the component's `DataClassDictMixin` config schema class, if declared."""
    if not spec.config_schema_path:
        return None
    module_path, sep, attr_name = spec.config_schema_path.partition(":")
    if not sep or not module_path or not attr_name:
        raise ComponentError(
            f"Invalid config_schema_path {spec.config_schema_path!r}; expected 'module:ClassName'"
        )
    module = importlib.import_module(module_path)
    schema_cls = getattr(module, attr_name, None)
    if (
        not isinstance(schema_cls, type)
        or not is_dataclass(schema_cls)
        or not issubclass(schema_cls, DataClassDictMixin)
    ):
        raise ComponentError(
            f"Config schema {spec.config_schema_path!r} did not resolve to a DataClassDictMixin dataclass"
        )
    return schema_cls


async def async_save_component_config(
    coordination: CoordinationService,
    domain: str,
    config: Mapping[str, Any],
) -> None:
    """Persist a dynamic component configuration override in `CoordinationService`."""
    await coordination.set_value(
        f"{_COMPONENT_CONFIG_KEY_PREFIX}{domain}",
        json.dumps(dict(config), sort_keys=True),
    )


async def async_resolve_component_configs(
    server_config: ServerConfig,
    coordination: CoordinationService,
    specs: Sequence[BuiltinComponentSpec] = BUILTIN_COMPONENTS,
) -> dict[str, ResolvedComponentConfig]:
    """Resolve effective per-component configuration across `env > yaml > database > default`.

    When a component's configuration is supplied via `SUPERNOTE_*` environment
    variables or an explicit `config.yaml` section, that static configuration
    wins over any persisted `CoordinationService` entry (`component_config:<domain>`).
    Otherwise, a valid persisted JSON dictionary from `CoordinationService` is used,
    falling back to the component's default configuration.
    """
    static_configs = build_static_component_configs(server_config)
    static_sources = _resolve_static_component_sources(server_config)
    resolved: dict[str, ResolvedComponentConfig] = {}

    for spec in specs:
        domain = spec.domain
        static_cfg = copy.deepcopy(static_configs.get(domain, {}))
        static_source = static_sources.get(domain)

        if static_source is not None and static_source.is_static:
            enabled = is_component_enabled(spec, static_cfg)
            static_cfg["enabled"] = enabled
            logger.debug(
                "Resolved component %r from %s (enabled=%s)",
                domain,
                static_source,
                enabled,
            )
            resolved[domain] = ResolvedComponentConfig(
                domain=domain,
                config=static_cfg,
                enabled=enabled,
                source=static_source,
            )
            continue

        raw_db_json = await coordination.get_value(
            f"{_COMPONENT_CONFIG_KEY_PREFIX}{domain}"
        )
        if raw_db_json:
            schema_cls = load_component_config_schema(spec)
            try:
                parsed = json.loads(raw_db_json)
                if not isinstance(parsed, dict):
                    raise ValueError("Persisted component config must be a JSON object")
                if "enabled" in parsed and not isinstance(parsed["enabled"], bool):
                    raise ValueError("Component 'enabled' field must be a boolean")
                if schema_cls is not None:
                    schema_cls.from_dict(parsed)
                enabled = is_component_enabled(spec, parsed)
                db_cfg = {**static_cfg, **parsed, "enabled": enabled}
                logger.debug(
                    "Resolved component %r from database (enabled=%s)",
                    domain,
                    enabled,
                )
                resolved[domain] = ResolvedComponentConfig(
                    domain=domain,
                    config=db_cfg,
                    enabled=enabled,
                    source=ComponentConfigSource.DATABASE,
                )
                continue
            except (
                json.JSONDecodeError,
                InvalidFieldValue,
                MissingField,
                ValueError,
                TypeError,
                KeyError,
            ) as err:
                logger.warning(
                    "Ignoring invalid persisted component config for %s: %s",
                    domain,
                    err,
                )

        enabled = is_component_enabled(spec, static_cfg)
        default_cfg = {**static_cfg, "enabled": enabled}
        logger.debug(
            "Resolved component %r from default (enabled=%s)",
            domain,
            enabled,
        )
        resolved[domain] = ResolvedComponentConfig(
            domain=domain,
            config=default_cfg,
            enabled=enabled,
            source=ComponentConfigSource.DEFAULT,
        )

    # Legacy one-off: `oauth` inherits `mcp`'s resolved enabled state and source when not configured directly.
    mcp_entry = resolved.get("mcp")
    oauth_entry = resolved.get("oauth")
    if (
        mcp_entry is not None
        and oauth_entry is not None
        and oauth_entry.source is ComponentConfigSource.DEFAULT
        and mcp_entry.source is not ComponentConfigSource.DEFAULT
    ):
        oauth_cfg = {**oauth_entry.config, "enabled": mcp_entry.enabled}
        resolved["oauth"] = ResolvedComponentConfig(
            domain="oauth",
            config=oauth_cfg,
            enabled=mcp_entry.enabled,
            source=mcp_entry.source,
        )

    return resolved


class ConfigService:
    """Service managing dynamic component configuration resolution and persistence."""

    def __init__(
        self,
        server_config: ServerConfig,
        coordination: CoordinationService,
        loader: ComponentLoader,
        specs: Sequence[BuiltinComponentSpec] = BUILTIN_COMPONENTS,
    ) -> None:
        self._server_config = server_config
        self._coordination = coordination
        self._loader = loader
        self._specs = tuple(specs)

    async def resolve_all(self) -> dict[str, ResolvedComponentConfig]:
        """Resolve effective configuration and source tiers for all built-in components."""
        return await async_resolve_component_configs(
            self._server_config,
            self._coordination,
            specs=self._specs,
        )


CONFIG_SERVICE_KEY: web.AppKey[ConfigService] = web.AppKey("config_service")
