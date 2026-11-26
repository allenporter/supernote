# ADR 0003: Component Configuration and Runtime Reconfiguration Architecture

- **Status**: Accepted (Implemented)
- **Date**: 2026-11-25
- **Scope**: `supernote.server.config`, `supernote.server.components.config`, `BuiltinComponentSpec`, and per-component configuration schemas

---

## 1. Context and Problem

As `supernote.server` evolved from a monolithic application factory into the `ServerCore` + vertical `Component` architecture ([ADR 0001](0001-server-core-component-architecture.md)), component configuration remained split across two patterns:

1. **Legacy flat attributes on `ServerConfig` ([`supernote/server/config.py`](../../../supernote/server/config.py))**: Several components (`mcp`, `metrics`, `web_ui`, `conversion`, `processor`, `events`, `http`, `ai`, `gemini`, `openai`) historically read flat top-level fields directly from `core.config` (e.g., `core.config.mcp_enabled`, `core.config.mcp_port`, `core.config.metrics_path`, `core.config.web_notebook_preview`, `core.config.event_log_retention_days`) and ignored the `config: Mapping[str, Any]` dictionary passed into `Component.async_setup(core, config)`.
2. **Typed per-component config dataclasses**: Newer vertical components (`webhooks`, `wiki`) define their own `mashumaro` `DataClassDictMixin` config dataclasses ([`WebhookConfig`](../../../supernote/server/components/webhooks/config.py), [`WikiConfig`](../../../supernote/server/components/wiki/config.py)) validated from the `config` mapping passed to `async_setup(core, config)`.

At the same time, self-hosted operators need two complementary ways to configure components:
- **Declarative / Infrastructure-as-Code**: Pinning settings via `SUPERNOTE_*` environment variables or `config.yaml` in container/Compose deployments.
- **Dynamic UI Configuration**: Enabling, disabling, or tuning unpinned components from the Web UI without hand-editing YAML files on disk.

---

## 2. Target End-State Architecture

### 2.1 Four-Tier Priority Resolution (`ComponentConfigSource`)

Every component's effective configuration is resolved by the `config` vertical component ([`supernote/server/components/config/`](../../../supernote/server/components/config/__init__.py)) across four priority tiers (`ComponentConfigSource`):

```
SUPERNOTE_* Env Vars (env)  >  config.yaml (<domain>:) (yaml)  >  Database (CoordinationService) (database)  >  Component Default (default)
```

- **Static tiers (`env`, `yaml`)**: When a component is explicitly configured via environment variables or `config.yaml`, that static configuration takes precedence over any database override and marks the component read-only (`readOnly: true`) in the management API and Web UI. Never auto-writing a default `config.yaml` file on first boot ensures that default values do not masquerade as explicit `yaml` overrides.
- **Dynamic tier (`database`)**: When a component is not pinned by `env` or `yaml`, `ConfigService` resolves any persisted JSON configuration from `CoordinationService` (`component_config:<domain>`), validates it against the component's schema dataclass, and falls back to `default` if absent or invalid.

### 2.2 Root-Level `<domain>:` Sections in `config.yaml`

In the target end state, `config.yaml` is organized around root-level `<domain>:` sections matching each component's `BuiltinComponentSpec.domain`:

```yaml
# Core server host settings remain at the top level of ServerConfig
host: 0.0.0.0
port: 8080
storage_dir: storage
log_level: INFO

auth:
  enable_registration: false

# Each vertical component owns its root-level <domain>: section
mcp:
  enabled: true
  port: 8081

metrics:
  enabled: true
  path: /metrics

web_ui:
  enabled: true

conversion:
  enabled: true
  notebook_preview: true

webhooks:
  enabled: true
  endpoints:
    - url: https://example.com/hook
      user: alice@example.com
      secret: shared-hmac-secret

wiki:
  enabled: true
  auto_compile: true
```

`ServerConfig` retains only core server host and authentication settings (`host`, `port`, `base_url`, `storage_dir`, `log_level`, `trace_log_*`, `default_user_quota`, `auth`), while each component owns its `<domain>:` configuration section.

### 2.3 Per-Component `DataClassDictMixin` Schemas (`config_schema_path`)

Every configurable built-in component declares a `config_schema_path` on its [`BuiltinComponentSpec`](../../../supernote/server/components/__init__.py) pointing to a `mashumaro` `DataClassDictMixin` dataclass in `supernote/server/components/<domain>/config.py`:

1. **Single input path (`async_setup(core, config)`)**: Each component parses its typed config dataclass from the `config: Mapping[str, Any]` argument passed to `async_setup(core, config)` (e.g., `self._config = McpConfig.from_dict(config)`) instead of reading flat attributes off `core.config`.
2. **Schema-driven validation and UI introspection**: `ConfigService` lazily loads `config_schema_path` via `load_component_config_schema(spec)` to validate persisted database configs and incoming `PUT /api/extended/system/components/{domain}` payloads, and extracts declarative `ComponentFieldSpecVO` descriptors (`name`, `type`, `default`) so the Web UI can render component settings without hardcoding per-component forms.
3. **Default `enabled` schema for simple components**: Components with no domain-specific settings beyond an `enabled` toggle expose a single boolean `enabled` field defaulting to `spec.default_enabled`.

### 2.4 Runtime Reconfiguration vs. Restart-Required Components

`BuiltinComponentSpec.runtime_configurable` distinguishes between components that can be reconfigured live in a running server and those bound to startup-frozen hosts:

- **Live-reconfigurable (`runtime_configurable=True`)**: Components whose lifecycle is self-contained in `async_setup` / `async_start` / `async_stop` (such as `webhooks`, which subscribes to `core.event_bus` and manages its own outbound `aiohttp.ClientSession`) are stopped and restarted live via `ComponentLoader.async_reconfigure` when updated through `ConfigService.update_component_config`.
- **Restart-required (`runtime_configurable=False`)**: Components that register routes or tools onto platforms finalized and frozen during startup (such as `aiohttp`'s frozen router on the `http` platform or FastMCP on the `mcp` platform) still allow their configuration to be edited and persisted to `CoordinationService` (when not pinned by `env`/`yaml`), returning `restartRequired: true` (`enabled != running`) until the next server restart.

---

## 3. Transitional Bridge to the End State

To reach this end state incrementally through small, backward-compatible PRs:

1. **Declarative field alias metadata on `ServerConfig`**: While legacy flat fields (`mcp_enabled`, `metrics_enabled`, `web_enabled`, etc.) exist on `ServerConfig`, they carry `field(metadata={"component": (domain, key)})`. `ServerConfig.load()` and `build_static_component_configs()` ([`supernote/server/components/config/service.py`](../../../supernote/server/components/config/service.py)) use this metadata generically to synchronize legacy flat fields with root `<domain>:` sections in both directions.
2. **Per-component schema migration**: Every configurable component (`mcp`, `metrics`, `conversion`, `processor`, `events`, `http`, `ai`, `gemini`, `openai`, `webhooks`, `wiki`) defines its own `supernote/server/components/<domain>/config.py` dataclass and `config_schema_path` on `BuiltinComponentSpec`, consuming its typed schema from `async_setup(core, config)` while `build_static_component_configs()` preserves backward compatibility with legacy flat `config.yaml` fields and `SUPERNOTE_*` environment variables.
