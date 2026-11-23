# ADR 0001: ServerCore and Vertical Component Architecture

- **Status**: Accepted (Phases 1–2 implemented; Phases 3–4 incremental rollout)
- **Date**: 2026-11-23
- **Scope**: `supernote.server` core host, component lifecycle, plugin discovery, Web UI extension slots, and persistence boundaries

---

## 1. Context and Goals

`supernote.server` runs as a single self-contained Python `asyncio` application built on `aiohttp`, SQLAlchemy 2.0 (`aiosqlite`), `LocalEventBus`, `LocalBlobStorage`, and a no-build Vue 3 ESM Web UI (see [Server Architecture](../../supernote/server/ARCHITECTURE.md)). Currently, [`create_app`](../../supernote/server/app.py) centrally constructs every service, attaches all 10 `web.RouteTableDef` modules, wires Socket.IO, mounts static assets, starts background workers (`ProcessorService`, `WebhookService`, `StorageMetricsCollector`, MCP OAuth + FastMCP server), and tears them down in nested `on_startup_handler` and `on_shutdown_handler` closures.

This architecture introduces a Home Assistant-inspired **core host + vertical components** model (`ServerCore` + `Component`) so that:

1. **Core hardware-sync primitives stay strongly typed and reliable**, providing a stable foundation for physical Supernote tablet synchronization, authentication, VFS, and blob storage.
2. **Feature domains and third-party extensions share a single uniform `Component` contract** with deterministic dependency ordering, fail-fast cycle/missing-dependency checks, and rollback-safe async lifecycle hooks.
3. **Adoption proceeds incrementally via small, independently shippable PRs** (~150–300 LoC each) using a strangler pattern, preserving wire-protocol compatibility, shared `supernote.models`, linear `supernote.alembic` migrations, and `tests/test_init.py` / `tests/server/db/models/test_init.py` conformance invariants.

---

## 2. `ServerCore`: Typed Core Host and Hardware-Sync Boundary

### 2.1 Core Service Ownership

`ServerCore` ([`supernote/server/core.py`](../../supernote/server/core.py)) is an **immutable** (`@dataclass(frozen=True)`), strongly-typed host passed to every component during setup, startup, and shutdown. It exposes direct, typed references to mandatory core infrastructure while keeping [`ComponentLoader`](../../supernote/server/core.py) owned separately by `create_app` so components cannot mutate core host references or invoke server-wide lifecycle transitions:

| Attribute | Verified Type & Module (`origin/main`) | Responsibility |
| :--- | :--- | :--- |
| `config` | [`ServerConfig`](../../supernote/server/config.py) | Resolved YAML + environment configuration (`storage_dir`, `auth`, `ai`, `webhooks`, `mcp_*`, `metrics_*`, `web_*`) |
| `app` | `aiohttp.web.Application` | HTTP router, middleware pipeline, and `aiohttp` lifecycle hooks |
| `event_bus` | [`LocalEventBus`](../../supernote/server/events.py) | In-process async pub/sub event bus (`subscribe`, `publish`) |
| `session_manager` | [`DatabaseSessionManager`](../../supernote/server/db/session.py) | Async SQLAlchemy engine, `session()` context manager, `close()` |
| `coordination` | [`CoordinationService`](../../supernote/server/services/coordination.py) (`SqliteCoordinationService`) | TTL key-value coordination store backed by [`KeyValueDO`](../../supernote/server/db/models/kv.py) (`key_values`) |
| `blob_storage` | [`BlobStorage`](../../supernote/server/services/blob.py) (`LocalBlobStorage`) | Content-addressable blob storage (`USER_DATA_BUCKET`, `CACHE_BUCKET`) |
| `user_service` | [`UserService`](../../supernote/server/services/user.py) | Accounts, password/challenge auth, device bindings, stateful JWT & `sn_...` API key verification |
| `file_service` | [`FileService`](../../supernote/server/services/file.py) | VFS tree orchestration (with per-session [`VirtualFileSystem`](../../supernote/server/services/vfs.py)), quotas, upload/download commit, blob GC |

Core device synchronization and authentication modules remain **part of the concrete core** rather than optional plugins:

- **Device & Auth Routes**: [`auth`](../../supernote/server/routes/auth.py), [`file_device`](../../supernote/server/routes/file_device.py) (`/api/file/2/*`, `/api/file/3/*`), [`file_web`](../../supernote/server/routes/file_web.py), [`oss`](../../supernote/server/routes/oss.py) (`/api/oss/*`), [`system`](../../supernote/server/routes/system.py), and [`admin`](../../supernote/server/routes/admin.py) / [`events`](../../supernote/server/routes/events.py) (until domain-specific admin/extended endpoints are cleanly split).
- **Auth & Security Pipeline**: [`jwt_auth_middleware`](../../supernote/server/app.py), [`static_cache_control_middleware`](../../supernote/server/app.py), [`trace_middleware`](../../supernote/server/trace.py), `aiohttp_remotes` proxy setup, [`@public_route` and `@interactive_session_only`](../../supernote/server/routes/decorators.py), [`get_token_from_request`](../../supernote/server/utils/auth_utils.py), [`RateLimiter`](../../supernote/server/utils/rate_limit.py), and [`UrlSigner`](../../supernote/server/utils/url_signer.py) (initialized in startup after `run_migrations` and `await user_service.get_secret_key()`).

Keeping these hardware-sync primitives concrete and statically typed on `ServerCore` ensures:

1. Physical Supernote tablet sync (`/api/file/2/*`, `/api/file/3/*`, `/api/oss/*`, `sync:lock:{user_id}`) and stateful JWT / API key auth can never be accidentally omitted or mis-ordered.
2. Components receive explicit, type-checked dependencies (`ty check`) without dynamic string-keyed service locator lookups.
3. Startup ordering between Alembic migrations, `UrlSigner` secret resolution, and dependent components remains deterministic.

### 2.2 Interaction with `supernote/server/keys.py` During Strangler Transition

[`supernote/server/keys.py`](../../supernote/server/keys.py) currently exports 24 `web.AppKey` singletons and 2 `web.RequestKey` keys (`REQUEST_USER_KEY`, `REQUEST_EQUIPMENT_NO_KEY`). During the incremental strangler migration:

- **Request keys stay**: `REQUEST_USER_KEY` and `REQUEST_EQUIPMENT_NO_KEY` remain the canonical per-request authentication context populated by `jwt_auth_middleware`.
- **Bridge key (`CORE_KEY`) `[Planned]`**: When `ServerCore` is wired into `create_app` (Phase 2), `app[CORE_KEY] = core` exposes `ServerCore` alongside existing `AppKey` entries so unmigrated `RouteTableDef` handlers continue reading `app[FILE_SERVICE_KEY]`, `app[USER_SERVICE_KEY]`, etc. without a flag day.
- **Typed inter-component APIs & per-PR key retirement**:
  - Private/internal keys with no cross-component consumers are retired when their component migrates (e.g., `WEBHOOK_SERVICE_KEY`, `STORAGE_METRICS_COLLECTOR_KEY`, `SOCKETIO_MANAGER_KEY`, `MCP_TASK_KEY`).
  - When a component exposes a typed service consumed by other components or external plugins (e.g., `mcp` or a plugin declaring `dependencies = ("search",)`), the providing component defines and exports its own typed `web.AppKey[T]` (e.g., `SEARCH_SERVICE_KEY`) and populates `core.app[KEY]` during `async_setup`. Dependent components read `core.app[KEY]` with full `ty check` type safety.

---

## 3. Uniform `Component` Protocol, Discovery, and Lifecycle Semantics

### 3.1 `Component` Protocol

All built-in vertical components and external third-party plugins implement [`Component`](../../supernote/server/core.py) (`@runtime_checkable` `typing.Protocol`):

```python
@runtime_checkable
class Component(Protocol):
    @property
    def domain(self) -> str: ...
    @property
    def dependencies(self) -> Sequence[str]: ...
    @property
    def platforms(self) -> Sequence[str]: ...
    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None: ...
    async def async_start(self, core: ServerCore) -> None: ...
    async def async_stop(self, core: ServerCore) -> None: ...
```

- **`domain`**: Unique lowercase identifier matching `^[a-z][a-z0-9_]*$` (e.g., `"http"`, `"mcp"`, `"metrics"`, `"oauth"`, `"schedule"`, `"socketio"`, `"web_ui"`, `"webhooks"`). Invalid or empty domains fail fast with `ComponentError`; duplicates raise `DuplicateComponentError`.
- **`dependencies`**: Ordered sequence of `domain` strings that must complete `async_setup` and `async_start` before this component (and execute `async_stop` after it).
- **`platforms`**: Ordered sequence of platform names implemented by this component (e.g., `("http",)`, `("http", "mcp")`), loaded lazily via `ComponentLoader.async_load_platform(platform, core, registrar)` calling `<component_pkg>.<platform>:async_setup_<platform>(core, registrar)`.

### 3.2 Discovery: Built-In Components (`BUILTIN_COMPONENTS`) and External Plugins

Both built-in components and third-party plugins register into the same [`ComponentLoader`](../../supernote/server/core.py) owned by `create_app`, allowing external plugins to depend on built-in component domains (for example, `dependencies = ("search",)`):

1. **Built-In Vertical Components ([`supernote/server/components/`](../../supernote/server/components/__init__.py))**:
   - Self-contained packages under `supernote/server/components/<domain>/` (`http`, `mcp`, `metrics`, `oauth`, `schedule`, `socketio`, `web_ui`, `webhooks`) with 1:1 mirrored tests under `tests/server/components/<domain>/`.
   - Declared centrally in `BUILTIN_COMPONENTS` (`BuiltinComponentSpec(domain, import_path, default_enabled)`) and loaded lazily by `load_builtin_components(loader, component_configs)` so disabled components are never imported.
   - **Config convention**: Legacy flat `ServerConfig` keys (`mcp_enabled`, `metrics_enabled`, `web_enabled`, etc.) remain on `ServerConfig` for backwards-compatible `config.yaml` files, while new/isolated components (e.g., [`webhooks/config.py`](../../supernote/server/components/webhooks/config.py)) own their own `mashumaro` config schema parsed from the per-domain `config: Mapping[str, Any]` dict in `async_setup`.
   - **Platform conformance**: `KNOWN_PLATFORMS` and [`tests/server/components/test_init.py`](../../tests/server/components/test_init.py) enforce 1:1 parity between `BUILTIN_COMPONENTS`, disk packages, declared `platforms` $\leftrightarrow$ `<platform>.py` modules, lazy imports, and cross-component import isolation.
   - Core routes and instrumentation libraries that other core modules import directly (such as [`supernote/server/metrics.py`](../../supernote/server/metrics.py) counters/histograms) remain shared core modules rather than being hidden inside optional component internals.

2. **External Third-Party Plugins (`importlib.metadata` `[Planned]`)**:
   - Discovered via `importlib.metadata.entry_points(group="supernote.server_components")` (sorted deterministically by entry-point `name`).
   - Each entry point resolves either a `Component` instance or a zero-argument callable returning a `Component` (`create_component() -> Component`).
   - Validated against `isinstance(component, Component)` before `loader.register(component)` so duplicate domains, invalid domains, missing dependencies, and cycles are caught identically to built-in components.
   - Plugin HTTP routes must mount under `/api/ext/<domain>/*` (protected by `jwt_auth_middleware` unless decorated with `@public_route` or explicitly exempted).

### 3.3 Topological Ordering and Failure / Shutdown Semantics

[`ComponentLoader`](../../supernote/server/core.py) enforces explicit lifecycle states (`IDLE -> SETUP -> STARTED -> STOPPED`), deterministic graph resolution, and transactional rollback:

1. **Dependency Validation (`resolve_order`)**:
   - Rejects `register()` calls once setup has started (`_LifecycleState.IDLE` required) and rejects duplicate `async_setup_all()` / `async_start_all()` calls.
   - Verifies every declared dependency exists in the registry; missing dependencies raise `MissingDependencyError(domain, dependency)` naming both requester and missing domain.
   - Uses Python stdlib `graphlib.TopologicalSorter` (`prepare()` converts `graphlib.CycleError` into `DependencyCycleError(cycle)` for both self-cycles and multi-node cycles) paired with a min-heap keyed by registration index over `get_ready()` / `done()`, guaranteeing deterministic topological order that preserves registration order for all tie-breaks.

2. **Mapping to `aiohttp` Lifecycle (`on_startup` / `on_shutdown` / `on_cleanup`)**:
   In `aiohttp`, `app.router` and `app.middlewares` remain mutable during `on_startup` (prior to `app.freeze()`), and an exception raised in `on_startup` invokes `on_cleanup` rather than `on_shutdown`. Furthermore, middleware order is security- and observability-critical (`socketio_compat_middleware` and `metrics_middleware` must wrap *outside* `trace_middleware` and `jwt_auth_middleware` so `EIO=3` query rewriting runs first and `401`/`403` responses are counted in Prometheus). Therefore, server startup executes in this exact sequence:
   1. Configure `aiohttp_remotes` proxy handling.
   2. Run database migrations: `await asyncio.to_thread(run_migrations, config.db_url, config=config)`.
   3. Initialize `UrlSigner` from `await user_service.get_secret_key()` and perform ephemeral user bootstrap if `config.ephemeral`.
   4. `await loader.async_setup_all(core)` — resolves topological order up front and runs `await comp.async_setup(core)` in dependency order to register component routes, event subscriptions, Web UI slots, pre-auth/post-auth middlewares, and public-prefix/ASGI auth exemptions (via Phase 2a registration hooks on `ServerCore` rather than raw `app.middlewares.append`). Components must **not** spawn persistent background tasks in `async_setup`. Note: because component routes register during `on_startup`, tests inspecting component routes must start the `aiohttp` app (e.g., via `TestServer` or invoking `loader.async_setup_all(core)`).
   5. Assemble the ordered middleware stack (`[...outer/pre-auth component middlewares, trace_middleware, jwt_auth_middleware, static_cache_control_middleware, ...inner/post-auth component middlewares]`), guaranteeing `socketio` and `metrics` always wrap outside `trace_middleware` and `jwt_auth_middleware`.
   6. `await loader.async_start_all(core)` — runs `await comp.async_start(core)` in dependency order to launch background workers, outbound HTTP sessions, or auxiliary servers (e.g., MCP port `8081`).
   7. **Unified Rollback & Shutdown**: Any `BaseException` (including `Exception` and `asyncio.CancelledError`) during `async_setup_all` or `async_start_all` triggers `await loader.async_stop_all(core)` before re-raising, stopping all initialized components in reverse topological order (with per-component `Exception` isolation so one failing `async_stop` never blocks earlier components from tearing down). On `on_shutdown` and `on_cleanup`, `await loader.async_stop_all(core)` runs idempotently (even if startup stopped after `async_setup_all` without reaching `async_start_all`). Because [`DatabaseSessionManager.close()`](../../supernote/server/db/session.py) is **not** idempotent (it raises `DatabaseError` if called twice), it runs **once** in `on_cleanup` after `await loader.async_stop_all(core)` (or is guarded).

---

## 4. Web UI Extension Slots

The Web UI ([`supernote/server/static/index.html`](../../supernote/server/static/index.html)) uses **no-build browser ES modules** with a `<script type="importmap">` (`"vue"`, `"marked"`, `"dompurify"`), Tailwind Play CDN (`darkMode: 'class'`), hash routing in [`useRouter.js`](../../supernote/server/static/js/composables/useRouter.js), and `x-access-token` header auth in `http.js` ([`supernote/server/static/js/api/http.js`](../../supernote/server/static/js/api/http.js)). Components extend the UI without a frontend build step:

1. **Backend Slot & Static Registration (`Component.async_setup`) `[Planned]`**:
   - `UiSlotContribution` dataclass registered on `ServerCore` (`UiExtensionRegistry`):
     - `plugin_domain: str` (must match the registering component's `domain`)
     - `slot_id: Literal["nav_tab", "system_section", "viewer_side_tab", "file_action"]`
     - `id: str`, `label: str` (plain text), `module_url: str`, `export_name: str = "default"`
     - `route_path: str | None = None` (maps `"nav_tab"` slots to `#/ext/<domain>/<id>`)
     - `icon_svg_path: str | None = None`, `requires_admin: bool = False`
   - `core.register_component_static(domain: str, directory: Path)` mounts `/components/<domain>/static/` via `app.router.add_static(...)`.
   - `jwt_auth_middleware` and `static_cache_control_middleware` exempt paths matching strictly `/components/<domain>/static/...` (the registered component static mount, never a broad `/components/` prefix), treating them identically to `/static/` (unauthenticated static read with `Cache-Control: no-cache` so ES modules revalidate across upgrades).

2. **Authenticated Manifest (`GET /api/extended/ui/manifest`) `[Planned]`**:
   - Protected by `jwt_auth_middleware` (`401` when unauthenticated).
   - Filters out `requires_admin=True` slots when `not user.is_admin`.
   - Returns `UiManifestVO` (`slots: list[UiSlotVO]`) defined in `supernote/models/extended.py` `[Planned]`. Fetched in [`main.js`](../../supernote/server/static/js/main.js) upon login/session restore and cleared on `onLogout`.

3. **Frontend Consumption, Routing & Security Invariants**:
   - **Dynamic ESM Loading**: `main.js` loads `import(slot.moduleUrl)` (sharing `"vue"`, `"marked"`, `"dompurify"` via the existing `<script type="importmap">`) inside Vue `defineAsyncComponent` + `onErrorCaptured` so a faulty component degrades gracefully inside its slot container.
   - **Scoped Host Context**: Slot components receive `{ apiRequest, showToast, openFile, navigateToHash }` props rather than raw JWT strings or `localStorage` access.
   - **Hash Routing**: `parseUrlHash` and `buildUrlHash` in `useRouter.js` extend canonical routes (`#/files`, `#/file/<id>`, `#/tasks`, `#/system`) with `#/ext/<domain>/<id>`.
   - **Same-Origin `module_url`, XSS, CSRF, and CSP**:
     - `UiExtensionRegistry` validates `module_url` as a normalized same-origin path under `/components/<domain>/static/` or `/static/` (rejecting `..`, `//`, `http:`, `https:`, `data:`, `javascript:`).
     - Slot labels render via Vue text interpolation (`{{ slot.label }}`, never `v-html`); any rich text must sanitize with `dompurify` from the import map.
     - `/api/ext/<domain>/*` routes use header-based `x-access-token` / `Authorization: Bearer` auth via `jwt_auth_middleware` (CSRF-safe; any cookie-authenticated route must enforce `GET /api/csrf` / `X-XSRF-TOKEN`), and [`oss.py`](../../supernote/server/routes/oss.py) retains its strict sandbox CSP (`default-src 'none'; ... sandbox`) on user-uploaded blobs.

---

## 5. Codebase, Model, and Persistence Invariants

### 5.1 Shared Wire Models (`supernote/models/`)

[`supernote/models/`](../../supernote/models/__init__.py) defines `mashumaro` `DataClassJSONMixin` DTOs/VOs shared by `supernote.client`, `supernote.cli`, and `supernote.server`. It **must never** import `sqlalchemy` or `supernote.server`, and [`supernote/__init__.py`](../../supernote/__init__.py) preserves lazy loading via PEP 562 `__getattr__` (enforced by [`tests/test_init.py`](../../tests/test_init.py) and [`tests/server/test_init.py`](../../tests/server/test_init.py)). `ServerCore`, `Component`, and ORM `*DO` classes reside exclusively under `supernote/server/`.

### 5.2 Linear Alembic Chain & Multi-User Schema Conformance

- [`supernote/alembic/env.py`](../../supernote/alembic/env.py) imports [`Base`](../../supernote/server/db/base.py) and `supernote.server.db.models.*` into `Base.metadata`.
- [`supernote/alembic/versions/`](../../supernote/alembic/versions) maintains a single strictly linear migration chain (`0543a383957b` -> current linear head `a4b5c6d7e8f9`).
- [`tests/server/db/test_migrations.py`](../../tests/server/db/test_migrations.py) enforces `reflected_app_tables == set(Base.metadata.tables)`.
- [`tests/server/db/models/test_init.py`](../../tests/server/db/models/test_init.py) (`assert_metadata_user_id_conformance`) enforces that every non-internal, non-exempt table on `Base.metadata` has `user_id` (`nullable=False`), includes `user_id` in its primary key, and includes `user_id` in every unique constraint/index. Legacy exemption allowlists (`TABLES_WITHOUT_USER_ID_ALLOWLIST`, `TABLES_WITHOUT_USER_ID_IN_PK_ALLOWLIST`, `UNSCOPED_UNIQUE_CONSTRAINT_ALLOWLIST`) **must never be expanded**.

### 5.3 Storage Rules: Built-In Components vs. Third-Party Plugins

| Dimension | Built-In Vertical Components (`supernote/server/components/<domain>/`) | External Third-Party Plugins (`importlib.metadata`) |
| :--- | :--- | :--- |
| **Core `Base.metadata` & Alembic** | May define `*DO` models on `Base`, re-export via [`supernote/server/db/models/__init__.py`](../../supernote/server/db/models/__init__.py), and add a linear revision in `supernote/alembic/versions/` (see [Schema Migration Guide](../schema_migration_guide.md)). | **Forbidden** from registering tables on `Base.metadata` or modifying core `supernote/alembic/versions/`. |
| **Multi-User Schema Rules** | Every new table must satisfy `assert_metadata_user_id_conformance` with `user_id` in columns, PK, and unique constraints (no allowlist additions). | Isolated per plugin; must still enforce `user_id` scoping on all per-user queries/paths. |
| **Ephemeral / Lock / Counter KV** | May use `core.coordination` (`CoordinationService`) with domain-prefixed keys. | Use `core.coordination` with strict `plugin:<domain>:` or `plugin:<domain>:<user_id>:` prefixes. Note [`SqliteCoordinationService`](../../supernote/server/services/coordination.py) semantics: `DEFAULT_TTL = 31536000` s (even `ttl=None` expires after 1 year), `set_value` uses `SELECT` + `UPDATE`/`INSERT` (non-atomic upsert), whereas `pop_value` (`DELETE ... RETURNING`) and `increment` (`INSERT ... ON CONFLICT DO UPDATE`) are atomic. |
| **Durable Relational / File State** | Core SQLite DB via `core.session_manager` and `core.blob_storage`. | Use dedicated plugin storage under `<config.storage_dir>/plugins/<domain>/` (e.g., plugin-owned SQLite DB with its own SQLAlchemy `MetaData` and migrations, or sanitized per-user subdirectories `<storage_dir>/plugins/<domain>/<user_id>/`). |

### 5.4 Test Parity Invariant

[`tests/test_init.py`](../../tests/test_init.py) (`test_all_test_files_conform_to_1to1_mapping`) requires every `.py` module under `supernote/` to map 1:1 to a mirror `test_*.py` under `tests/` (`ALLOWLIST_NON_CONFORMING_TESTS = set()`). Every new component module (`supernote/server/components/<domain>/*.py`) must ship with its exact mirror test module (`tests/server/components/<domain>/test_*.py`), and [`supernote/server/__init__.py`](../../supernote/server/__init__.py) must remain free of eager `app`/`sqlalchemy` imports (`tests/server/test_init.py`).

---

## 6. Incremental Strangler Roadmap

Each phase ships in small, independently tested PRs (~150–300 LoC of production code per PR) with zero forward dependencies.

### Phase 1: Minimal `ServerCore`, `Component` Protocol, `ComponentLoader`, and ADR (Current PR)
- Standalone [`supernote/server/core.py`](../../supernote/server/core.py) + [`tests/server/test_core.py`](../../tests/server/test_core.py) and this ADR.
- Zero changes to `app.py`, `supernote/models/`, `supernote/alembic/`, or conformance allowlists.

### Phase 2: Core Lifecycle Wiring + Self-Contained Vertical Components
1. **PR 2a — `ServerCore` Wiring in `app.py`**: Construct `ServerCore` and `ComponentLoader` in `create_app`, store `app[CORE_KEY] = core` `[Planned]`, add outer/inner middleware and public-prefix/ASGI exemption registration hooks so components integrate cleanly with `jwt_auth_middleware`, and invoke `await loader.async_setup_all(core)` / `await loader.async_start_all(core)` / `await loader.async_stop_all(core)` inside `on_startup_handler` and `on_shutdown_handler` / `on_cleanup` (behavior-preserving no-op with 0 components initially).
2. **PR 2b — `webhooks` ([`supernote/server/components/webhooks/`](../../supernote/server/components/webhooks/__init__.py))**: Vertical component owning [`WebhookService`](../../supernote/server/components/webhooks/service.py) (`config.webhooks`, `core.event_bus`, `core.user_service`); retires `WEBHOOK_SERVICE_KEY` and direct `webhook_service` wiring from `app.py`.
3. **PR 2c — `metrics` ([`supernote/server/components/metrics/`](../../supernote/server/components/metrics/__init__.py))**: Vertical component owning `GET {config.metrics_path}` and `create_metrics_middleware` via [`http.py`](../../supernote/server/components/metrics/http.py) (`pre_auth=True`) and [`StorageMetricsCollector`](../../supernote/server/components/metrics/storage.py), keeping metric definitions/helpers in [`supernote/server/metrics.py`](../../supernote/server/metrics.py) as a shared core instrumentation library.
4. **PR 2d — `socketio` ([`supernote/server/components/socketio/`](../../supernote/server/components/socketio/__init__.py))**: Vertical component owning [`SocketIOServerManager`](../../supernote/server/components/socketio/manager.py), `socketio_compat_middleware` (outer/pre-auth middleware), and `/socket.io` public prefix registration (retiring hardcoded `/socket.io` bypass in `jwt_auth_middleware` and `SOCKETIO_MANAGER_KEY` from `keys.py`); keeps [`socket_auth`](../../supernote/server/socket_auth.py) shared with `supernote.client` and `supernote.cli`.
5. **PR 2e — `oauth` & `mcp` ([`supernote/server/components/oauth/`](../../supernote/server/components/oauth/__init__.py), [`supernote/server/components/mcp/`](../../supernote/server/components/mcp/__init__.py))**: `oauth` owns [`provider.py`](../../supernote/server/components/oauth/provider.py), [`models.py`](../../supernote/server/components/oauth/models.py), and [`http.py`](../../supernote/server/components/oauth/http.py) (`ASGIResource` mount via `HttpRegistrar`); `mcp` depends on `oauth` (`dependencies = ("oauth",)`) and owns [`server.py`](../../supernote/server/components/mcp/server.py) and [`models.py`](../../supernote/server/components/mcp/models.py), retiring `MCP_ASGI_RESOURCE_KEY` and `MCP_TASK_KEY` from `app.py` and `keys.py`.

### Phase 3: External Plugins & Web UI Extension Slots
1. **PR 3a — Entry-Point Plugin Discovery**: Load `importlib.metadata.entry_points(group="supernote.server_components")` into `ComponentLoader` with `/api/ext/<domain>/*` prefix isolation and `<storage_dir>/plugins/<domain>/` path helper.
2. **PR 3b — Web UI Slot Registry & Manifest**: Add `UiSlotContribution`, `/components/<domain>/static/` mount + `Cache-Control: no-cache` + public static exemption, `GET /api/extended/ui/manifest`, and `main.js` / `useRouter.js` (`#/ext/<domain>/<id>`) dynamic ESM slot rendering.

### Phase 4: Explicit Pause-and-Reassess Gate (Horizontal Domains)

Before extracting any of the remaining horizontal domains—`summary`, `search`, or `processor`—implementation **must pause and reassess** against verified cross-domain coupling on `origin/main`:

- **`summary` ↔ Core VFS GC**: [`FileService._filter_unreferenced_summary_keys`](../../supernote/server/services/file.py) directly queries [`SummaryDO`](../../supernote/server/db/models/summary.py) (`SummaryDO.handwrite_inner_name`) during `cleanup_unreferenced_blobs`. Extracting `summary` requires a core blob-reference provider protocol on `ServerCore` (`register_blob_reference_provider`).
- **Cross-Table Audits**: [`IntegrityService`](../../supernote/server/services/integrity.py) joins 5 tables across 3 domains (`UserFileDO`, `RecycleFileDO`, `NotePageContentDO`, `SystemTaskDO`, `SummaryDO`), requiring an extensible integrity-check provider hook.
- **Account Deletion**: [`handle_account_clear`](../../supernote/server/routes/auth.py) (`TODO(#407)`) and `UserService.clear_account` require a core user-deletion hook before components can own user-scoped tables independently.
- **Note Pipeline & Search Sharing**: [`ProcessorService`](../../supernote/server/services/processor.py) requires `SummaryService` at construction; [`ConversionService`](../../supernote/server/services/conversion.py) and [`SearchService`](../../supernote/server/services/search.py) directly query `NotePageContentDO` alongside `UserFileDO`; and `SearchService` is consumed by both [`routes/extended.py`](../../supernote/server/routes/extended.py) and `mcp/server.py`.
- **Route & SPA Aggregation**: [`routes/admin.py`](../../supernote/server/routes/admin.py) directly imports `UserFileDO` and `SystemTaskDO` and invokes `PROCESSOR_SERVICE_KEY`; [`routes/extended.py`](../../supernote/server/routes/extended.py) aggregates 5 domains (`/file/summary/list`, `/system/tasks`, `/file/processing/status`, `/file/note/metadata`, `/search`, `/transcript`, `/ai/status`, `/file/note/cover`, `/keys`). Splitting these waits until Phase 3's Web UI slot architecture is proven in production.

**Gate Exit Criteria**: After Phase 3 lands, review observed plugin ergonomics and decide for each horizontal domain whether to introduce minimal core extension protocols (blob-reference provider, integrity-check provider, user-deletion hook, shared note-index boundary) or keep tightly-coupled core note services consolidated on `ServerCore`.

**Future Platform Evolution (`http`, `metrics`, `mcp`, `integrity`)**: Once multiple vertical components exist, cross-cutting transport and observability concerns can evolve into Home Assistant-style platforms where each domain contributes focused platform modules (for example, `components/<domain>/http.py` for `aiohttp` routes/middlewares, `components/<domain>/metrics.py` for Prometheus collectors, and `components/<domain>/mcp.py` for MCP tools) loaded by the corresponding platform host only when enabled.
