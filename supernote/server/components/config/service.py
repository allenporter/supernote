"""Configuration resolution and runtime reconfiguration service for built-in components.

Resolves effective per-component configuration across four priority tiers
(`env` > `yaml` > `database` > `default`) and orchestrates live runtime
reconfiguration via `ComponentLoader.async_reconfigure`.
"""

from __future__ import annotations

import asyncio
import copy
import importlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import MISSING, dataclass, fields, is_dataclass
from typing import TYPE_CHECKING, Any

from aiohttp import web
from mashumaro.exceptions import InvalidFieldValue, MissingField
from mashumaro.mixins.dict import DataClassDictMixin

from supernote.models.base import ErrorCode
from supernote.server.components import (
    BUILTIN_COMPONENTS,
    BuiltinComponentSpec,
    is_component_enabled,
    load_component_from_spec,
)
from supernote.server.config import ComponentConfigSource, ServerConfig
from supernote.server.core import ComponentError, ComponentLoader, ServerCore
from supernote.server.exceptions import (
    InvalidInputError,
    SupernoteError,
)

from .models import ComponentFieldSpecVO, ComponentFieldType, ComponentStatusVO

if TYPE_CHECKING:
    from supernote.server.services.coordination import CoordinationService

__all__ = [
    "CONFIG_SERVICE_KEY",
    "ConfigService",
    "ConfigurationConflictError",
    "ResolvedComponentConfig",
    "async_resolve_component_configs",
    "async_save_component_config",
    "build_static_component_configs",
    "extract_component_field_specs",
    "load_component_config_schema",
]

logger = logging.getLogger(__name__)

_COMPONENT_CONFIG_KEY_PREFIX = "component_config:"
_AI_PROVIDER_DOMAINS: frozenset[str] = frozenset(
    {"apple", "fake_ai", "gemini", "openai"}
)
# Components that host the HTTP server, Web UI, Config API itself, or test-only fakes
# cannot be disabled dynamically via the database/API (only via code, env, or config.yaml).
_PROTECTED_DYNAMIC_DOMAINS: frozenset[str] = frozenset(
    {"config", "fake_ai", "http", "web_ui"}
)


class ConfigurationConflictError(SupernoteError):
    """Raised when attempting to dynamically modify a component pinned by `env`/`yaml` or required by an active dependent."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            error_code=ErrorCode.CONFLICT_EXISTS,
            status_code=409,
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
    configs["ai"] = {
        **configs.get("ai", {}),
        **server_config.ai.to_dict(),
    }
    for domain in _AI_PROVIDER_DOMAINS:
        provider_entries = {
            name: p_cfg.to_dict()
            for name, p_cfg in server_config.ai.providers.items()
            if server_config.ai.provider_type(name).strip().lower() == domain
        }
        raw_domain_cfg = configs.get(domain, {})
        domain_cfg: dict[str, Any] = {
            **raw_domain_cfg,
            "enabled": bool(raw_domain_cfg.get("enabled", domain in ai_domains)),
        }
        if provider_entries:
            domain_cfg["providers"] = {
                **domain_cfg.get("providers", {}),
                **provider_entries,
            }
            if domain in provider_entries:
                for key in ("api_key", "base_url"):
                    if key in provider_entries[domain]:
                        domain_cfg.setdefault(key, provider_entries[domain][key])
        if (domain_cfg.get("api_key") or domain_cfg.get("base_url")) and domain not in (
            domain_cfg.get("providers") or {}
        ):
            entry: dict[str, Any] = {"type": domain}
            for key in ("api_key", "base_url"):
                if domain_cfg.get(key) is not None:
                    entry[key] = domain_cfg[key]
            domain_cfg["providers"] = {
                **(domain_cfg.get("providers") or {}),
                domain: entry,
            }
        raw_providers = domain_cfg.get("providers")
        if isinstance(raw_providers, dict):
            ai_providers = dict(configs["ai"].get("providers") or {})
            for p_name, p_val in raw_providers.items():
                if isinstance(p_val, dict):
                    ai_providers.setdefault(
                        p_name,
                        {**p_val, "type": p_val.get("type") or domain},
                    )
            if ai_providers:
                configs["ai"]["providers"] = ai_providers
        configs[domain] = domain_cfg
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
            if (
                target_key in server_config.root_component_configs.get(domain, {})
                and val == f.default
                and server_config.component_sources.get(domain)
                != ComponentConfigSource.ENV
            ):
                continue
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


def extract_component_field_specs(
    spec: BuiltinComponentSpec,
) -> list[ComponentFieldSpecVO]:
    """Extract declarative field descriptors from ``spec.config_schema_path`` (or default `enabled`)."""
    schema_cls = load_component_config_schema(spec)
    if schema_cls is None or not is_dataclass(schema_cls):
        return [
            ComponentFieldSpecVO(
                name="enabled",
                type=ComponentFieldType.BOOLEAN,
                default=spec.default_enabled,
            )
        ]
    result: list[ComponentFieldSpecVO] = []
    for f in fields(schema_cls):
        if f.name.startswith("_"):
            continue
        default_val: Any = None
        if f.default is not MISSING:
            default_val = f.default
        elif f.default_factory is not MISSING:
            default_val = f.default_factory()
        result.append(
            ComponentFieldSpecVO(
                name=f.name,
                type=ComponentFieldType.from_type_annotation(str(f.type)),
                default=default_val,
            )
        )
    return result


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

        # Legacy one-off: `oauth` inherits `mcp`'s resolved enabled state when not configured directly.
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
            source=ComponentConfigSource.DEFAULT,
        )

    return resolved


class ConfigService:
    """Service managing dynamic component configuration resolution, persistence, and runtime updates."""

    def __init__(
        self,
        core: ServerCore,
        loader: ComponentLoader,
        specs: Sequence[BuiltinComponentSpec] = BUILTIN_COMPONENTS,
    ) -> None:
        self._core = core
        self._server_config = core.config
        self._coordination = core.coordination
        self._loader = loader
        self._specs = tuple(specs)
        self._specs_by_domain = {spec.domain: spec for spec in self._specs}
        self._dependencies_by_domain: dict[str, tuple[str, ...]] = {}
        self._update_lock = asyncio.Lock()

    def _get_dependencies(self, domain: str) -> tuple[str, ...]:
        """Lazily resolve and cache ``domain``'s declared component dependencies."""
        deps = self._dependencies_by_domain.get(domain)
        if deps is None:
            spec = self._specs_by_domain[domain]
            existing = self._loader.get(domain)
            comp = existing if existing is not None else load_component_from_spec(spec)
            deps = tuple(comp.dependencies)
            self._dependencies_by_domain[domain] = deps
        return deps

    async def resolve_all(self) -> dict[str, ResolvedComponentConfig]:
        """Resolve effective configuration and source tiers for all built-in components."""
        return await async_resolve_component_configs(
            self._server_config,
            self._coordination,
            specs=self._specs,
        )

    def _build_status_vo(
        self,
        spec: BuiltinComponentSpec,
        entry: ResolvedComponentConfig,
    ) -> ComponentStatusVO:
        running = self._loader.is_running(spec.domain)
        read_only = entry.source.is_static or spec.domain in _PROTECTED_DYNAMIC_DOMAINS
        return ComponentStatusVO(
            domain=spec.domain,
            enabled=entry.enabled,
            running=running,
            source=entry.source,
            read_only=read_only,
            runtime_configurable=spec.runtime_configurable,
            restart_required=(entry.enabled != running),
            config=dict(entry.config),
            fields=extract_component_field_specs(spec),
        )

    async def list_component_statuses(self) -> list[ComponentStatusVO]:
        """Return runtime status and configuration for all built-in components."""
        resolved = await self.resolve_all()
        return [
            self._build_status_vo(spec, resolved[spec.domain]) for spec in self._specs
        ]

    def _validate_dependency_graph(
        self,
        domain: str,
        target_enabled: bool,
        resolved: Mapping[str, ResolvedComponentConfig],
    ) -> None:
        """Reject enabling a component with disabled dependencies or disabling one required by an enabled dependent."""
        if target_enabled:
            for dep in self._get_dependencies(domain):
                dep_entry = resolved.get(dep)
                if dep_entry is not None and not dep_entry.enabled:
                    raise ConfigurationConflictError(
                        f"Cannot enable component '{domain}' while required dependency '{dep}' is disabled."
                    )
            return

        for spec in self._specs:
            if spec.domain == domain:
                continue
            other_entry = resolved.get(spec.domain)
            if (
                other_entry is not None
                and other_entry.enabled
                and domain in self._get_dependencies(spec.domain)
            ):
                raise ConfigurationConflictError(
                    f"Cannot disable component '{domain}' while dependent component '{spec.domain}' is enabled."
                )

    async def update_component_config(
        self,
        domain: str,
        updates: Mapping[str, Any],
    ) -> ComponentStatusVO:
        """Merge ``updates`` onto ``domain``'s current config, validate, live-reconfigure if supported, and persist."""
        spec = self._specs_by_domain.get(domain)
        if spec is None:
            raise InvalidInputError(f"Unknown component domain: {domain!r}")
        if domain in _PROTECTED_DYNAMIC_DOMAINS:
            raise ConfigurationConflictError(
                f"Component '{domain}' cannot be modified dynamically via the API; configure it in config.yaml or environment variables."
            )

        async with self._update_lock:
            resolved = await self.resolve_all()
            current_entry = resolved[domain]
            if current_entry.source.is_static:
                raise ConfigurationConflictError(
                    f"Component '{domain}' is managed by {current_entry.source} configuration and is read-only."
                )

            merged_config: dict[str, Any] = {
                **current_entry.config,
                **dict(updates),
            }

            field_specs = extract_component_field_specs(spec)
            allowed_keys = {f.name for f in field_specs}
            extra_keys = set(updates.keys()) - allowed_keys
            if extra_keys:
                raise InvalidInputError(
                    f"Unexpected configuration field(s) for component '{domain}': "
                    f"{', '.join(sorted(extra_keys))}"
                )
            for f_spec in field_specs:
                # Mashumaro's default `bool` deserializer coerces ints/strings to booleans;
                # reject non-bool values explicitly so malformed payloads fail with 400.
                if (
                    f_spec.type is ComponentFieldType.BOOLEAN
                    and f_spec.name in merged_config
                    and not isinstance(merged_config[f_spec.name], bool)
                ):
                    raise InvalidInputError(
                        f"Component '{domain}' field '{f_spec.name}' must be a boolean."
                    )

            schema_cls = load_component_config_schema(spec)
            if schema_cls is not None:
                try:
                    validated = schema_cls.from_dict(merged_config)
                    merged_config = validated.to_dict()
                except (
                    InvalidFieldValue,
                    MissingField,
                    ValueError,
                    TypeError,
                    KeyError,
                ) as err:
                    raise InvalidInputError(
                        f"Invalid configuration for component '{domain}': {err}"
                    ) from err

            merged_config["enabled"] = is_component_enabled(spec, merged_config)
            self._validate_dependency_graph(
                domain, bool(merged_config["enabled"]), resolved
            )

            if spec.runtime_configurable:
                was_running = self._loader.is_running(domain)
                comp_instance = load_component_from_spec(spec)
                try:
                    await self._loader.async_reconfigure(
                        self._core, comp_instance, merged_config
                    )
                except ComponentError as err:
                    raise ConfigurationConflictError(
                        f"Cannot reconfigure component '{domain}': {err}"
                    ) from err
                except (ValueError, TypeError) as err:
                    if was_running and not self._loader.is_running(domain):
                        await self._loader.async_reconfigure(
                            self._core,
                            load_component_from_spec(spec),
                            current_entry.config,
                        )
                    raise InvalidInputError(
                        f"Failed to reconfigure component '{domain}': {err}"
                    ) from err

            await async_save_component_config(self._coordination, domain, merged_config)
            updated_entry = ResolvedComponentConfig(
                domain=domain,
                config=merged_config,
                enabled=bool(merged_config["enabled"]),
                source=ComponentConfigSource.DATABASE,
            )
            status_vo = self._build_status_vo(spec, updated_entry)
            logger.info(
                "Updated configuration for component %r (enabled=%s, running=%s, restart_required=%s)",
                domain,
                status_vo.enabled,
                status_vo.running,
                status_vo.restart_required,
            )
            return status_vo


CONFIG_SERVICE_KEY: web.AppKey[ConfigService] = web.AppKey("config_service")
