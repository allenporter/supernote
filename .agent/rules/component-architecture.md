# Server Component Architecture Rules

When creating or refactoring vertical components under `supernote/server/components/<domain>/`, follow these five rules (enforced by `tests/server/components/test_init.py`):

1. **One Role Per File**:
   - `__init__.py` — Lifecycle shell and public API only: defines `<Name>Component` (`domain`, `dependencies`, `platforms`, `async_setup`, `async_start`, `async_stop`) and re-exports component-owned `AppKey`s. No HTTP handlers or heavy business logic.
   - `http.py` *(when `"http"` is in `platforms`)* — All main-port HTTP transport: `async_setup_http(core, registrar)`, `aiohttp`/Starlette route handlers, middlewares, ASGI mounts, and auth exemptions.
   - `config.py` *(optional)* — Pure `mashumaro` config dataclasses and validation; zero service or transport imports.
   - `models.py` *(optional)* — Pure DTOs, VOs, and token models; zero service or transport imports.
   - `<domain>.py` (`service.py`, `provider.py`, `manager.py`, `storage.py`, `server.py`) — Transport-free domain logic depending only on `ServerCore` services, `config.py`, and `models.py`.

2. **Strict Transport Isolation (`http.py` is the only main-port HTTP boundary)**:
   - Non-`http.py` modules in a component must not import `aiohttp_asgi`, `supernote.server.components.http`, or `supernote.server.routes.decorators`.
   - Domain modules must be unit-testable without constructing main-port HTTP routes or middleware pipelines.

3. **Declared Dependencies & Platforms Only**:
   - A component (including all its submodules) may only import from `supernote.server.components.<other>` when `<other>` is listed in `component.dependencies` or `component.platforms`.
   - Every platform module on disk (`http.py`, future `metrics.py`, `mcp.py`) must be listed in `component.platforms` and define `async def async_setup_<platform>(core, registrar)`.

4. **Lazy Core Isolation**:
   - Core modules (`supernote.server.core`, `supernote.server.config`, `supernote.server.app`) must never eagerly import `supernote.server.components.*` at import time.
   - Register every built-in component in `BUILTIN_COMPONENTS` (`supernote/server/components/__init__.py`) so disabled components are never imported.

5. **Component-Owned State & Idempotent Lifecycle**:
   - Feature-specific `web.AppKey`s live inside the component that creates them—do not add feature keys to `supernote/server/keys.py`.
   - Every component must support `async_setup -> async_start -> async_stop -> async_stop` and `async_setup -> async_stop` cleanly without leaking tasks or subscriptions.
