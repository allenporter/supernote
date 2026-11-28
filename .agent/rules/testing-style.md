---
trigger: glob
globs: "**/tests/**"
description: Home Assistant-style component and SDK testing standards (prefer high-level clients, fakes, and shared fixtures).
---

# Testing Style & Component Testing Standards

Tests in this repository follow Home Assistant–style component testing norms: test behavior through the highest-level public boundary available, prefer real in-process infrastructure and fakes over mocks, and reuse shared harness fixtures.

## 1. Test Through High-Level Public Boundaries First

- **HTTP endpoints (`test_http.py`, `tests/server/routes/`)**: Exercise routes through the typed async SDK clients (`DeviceClient`, `WebClient`, `ExtendedClient`, `AdminClient`, `SummaryClient`, `ScheduleClient`, `EventsClient`, `WikiClient`, `LoginClient`) against the running in-process `aiohttp` `client`. Reserve raw `client.get`/`client.post` calls for malformed payloads, auth/header edge cases, or routes intentionally outside the SDK (e.g., `/metrics`, OAuth discovery, static Web UI routes).
- **MCP tools (`test_mcp.py`)**: Boot the real MCP platform (`mcp_enabled = True`) and invoke tools over `mcp_session` + `call_mcp_tool`. Do not invoke tool functions directly from `registrar._tools` or pass mocked `Context` objects.
- **Component lifecycle & services (`test_init.py`, `test_service.py`)**: Load components via the shared `load_components` fixture (which resolves transitive dependencies and tears down cleanly) and resolve services via their exported `AppKey` rather than manually wiring `ComponentLoader()` or constructing service objects with hand-built dependencies.
- **State setup via public APIs**: Prefer creating test state through public services (`UserService`, `FileService`, or typed HTTP clients) instead of inserting raw SQLAlchemy `DO` rows, unless testing a specific database/migration edge case or legacy schema state.

## 2. Prefer Fakes Over Mocks

- **Use real in-process test infrastructure**: Run against the shared SQLite `session_manager`, `LocalBlobStorage`, `LocalEventBus`, and deterministic `fake_ai` providers (`FakeOcrModel`, `FakeEmbeddingModel`, `FakeSummaryModel`, `FakeTextModel`) instead of mocking internal services or sessions.
- **Avoid mocking internal collaborators or the object under test**: Do not `MagicMock` internal services, `EventBus`, or private methods (`patch.object(sut, "_helper")`).
- **When `unittest.mock` is appropriate**:
  - External third-party SDK boundaries or OS/framework imports (`google.genai`, `openai`, Apple Vision frameworks).
  - Controlled fault injection for 500 / I/O error-handling paths (`side_effect=RuntimeError(...)`) that cannot be triggered deterministically through fakes.
  - Clock or environment variable isolation (`patch.dict(os.environ, ...)`, `time.time`).

## 3. Shared Harness Fixtures & Clean Isolation

- **Reuse centralized fixtures**: Use `tests/fixtures/server.py` (all typed clients, `client`, `authenticated_client`, `admin_client`, `session_manager`, `blob_storage`, `user_service`, `server_config`), `tests/server/conftest.py` (`event_bus`, `file_service`), and `tests/server/components/conftest.py` (`component_core`, `load_components`, `mcp_session`, `call_mcp_tool`). Do not redefine `authenticated_client`, `event_bus`, or typed client fixtures locally in individual test modules.
- **Core vs. component isolation**: Keep core tests (`tests/server/services/`, `tests/server/routes/`) decoupled from component ORM models and component internals; test core hooks (such as `BlobReferenceProvider`) with lightweight local fakes.

## 4. Structure & Async Hygiene

- **1:1 component test mirroring**: Mirror `supernote/server/components/<domain>/<module>.py` at `tests/server/components/<domain>/test_<module>.py` (and `__init__.py` at `test_init.py`). Keep service-level tests in `test_service.py` and HTTP route tests in `test_http.py`.
- **No `@pytest.mark.asyncio`**: `pyproject.toml` sets `asyncio_mode = "auto"`, so write plain `async def test_...():` functions without explicit `@pytest.mark.asyncio` decorators.
