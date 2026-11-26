# Contributing

We welcome bug fixes, documentation improvements, and feature contributions to **Open Private Cloud for Supernote**—across the `.note` parser/converter library, async Python SDK & CLI, and self-hosted server + Web UI.

## Picking Up Issues & Pull Request Sizing

Live priorities and active tracks are organized in **[ROADMAP.md](../ROADMAP.md)** and **[GitHub Milestones](https://github.com/allenporter/supernote/milestones)**:

- **Ready to implement (`agent-ready`)**: Browse the **[P1 Next-Up Queue](https://github.com/allenporter/supernote/issues?q=is%3Aopen+is%3Aissue+label%3Ap1+label%3Aagent-ready)** or **[Quick Polish Wins (`polish` + `agent-ready`)](https://github.com/allenporter/supernote/issues?q=is%3Aopen+is%3Aissue+label%3Apolish+label%3Aagent-ready)** for well-scoped tasks with clear acceptance criteria. Check [open Pull Requests](https://github.com/allenporter/supernote/pulls) first so you don't duplicate in-flight work.
- **Design alignment first (`needs-design`)**: Issues labeled **[`needs-design`](https://github.com/allenporter/supernote/issues?q=is%3Aopen+is%3Aissue+label%3Aneeds-design)** have open architectural, schema, or UX tradeoffs. Please discuss options on the issue and align on an approach *before* opening an implementation PR.
- **Small, incremental PRs (~150–300 LoC)**: Keep pull requests focused on a single cohesive slice that builds, migrates cleanly, and passes `./script/lint` and `./script/test` on its own. If a feature spans multiple layers (schema, backend service, SDK/CLI, Web UI) or exceeds ~300 lines of production code, propose an incremental PR breakdown on the issue first.

---

## Code Style & Standards

### Testing

This project uses `pytest` and `pytest-asyncio` with Home Assistant–style component testing norms:

- **High-level boundaries first**: Exercise HTTP routes through the typed async SDK clients (`DeviceClient`, `WebClient`, `ExtendedClient`, `AdminClient`, `SummaryClient`, `ScheduleClient`, `EventsClient`, `WikiClient`, `ConfigClient`), MCP tools through `mcp_session` + `call_mcp_tool`, and server components through the `load_components` fixture.
- **Fakes over mocks**: Prefer the real in-process SQLite `session_manager`, `LocalBlobStorage`, `LocalEventBus`, and `fake_ai` providers over `unittest.mock`; reserve mocks for external SDK boundaries, env/clock control, and targeted fault injection.
- **Async auto mode**: `pyproject.toml` configures `asyncio_mode = "auto"`, so write plain `async def test_...():` functions without `@pytest.mark.asyncio`.
- **Shared fixtures**: Server and typed-client harness fixtures live in `tests/fixtures/server.py`, core service fixtures in `tests/server/conftest.py`, and component/MCP harness fixtures in `tests/server/components/conftest.py`.
- **Structure**: Mirror component modules 1:1 (`supernote/server/components/<domain>/<module>.py` ↔ `tests/server/components/<domain>/test_<module>.py`).

### Typing & Data Models

- **Dataclasses**: Use standard Python `dataclasses` with `DataClassJSONMixin`.
- **Serialization**: Use `mashumaro`.
- **Strictness**: Define explicit types for all DTOs in `supernote.models`.

### Server Architecture

The server is built around a concrete core host (`ServerCore` in `supernote/server/core.py`) for device sync, VFS, auth, and SQLite coordination, plus 22 lazy-loaded vertical components under `supernote/server/components/<domain>/` registered in `BUILTIN_COMPONENTS`. Each component declares its dependencies and platform modules (`http.py`, `mcp.py`, `processor.py`, `ocr.py`, `summary.py`, `embedding.py`, `text.py`) so disabled domains are never imported.

See the [Server Component Catalog](./architecture/components.md), [ADR 0001](./architecture/adr/0001-server-core-component-architecture.md), and [Server & Sync Protocol Architecture](./architecture/server_architecture.md) before adding routes, services, or new components.

---

## Local Development Setup

We use standard scripts in the `script/` directory following the "Scripts to Rule Them All" pattern.

### Environment Setup

```bash
./script/bootstrap
```

This script will initialize a virtual environment using `uv`, install dependencies (`.[all]`), and set up `pre-commit` hooks.

### Standard Scripts

| Script | Purpose |
| :--- | :--- |
| `script/bootstrap` | Initial environment setup and dependency installation. |
| `script/setup` | Setup the project and help with venv activation. |
| `script/update` | Pulls latest changes and re-runs bootstrap. |
| `script/test` | Runs the full test suite using `pytest`. |
| `script/lint` | Runs linters and style checks via `pre-commit`. |
| `script/docs` | Builds or live-serves the multi-level `pdoc` documentation site (`./script/docs -o site/` or `./script/docs --serve`). |
| `script/server` | Starts an ephemeral development server. |

---

## Development Workflow

### Ephemeral Mode

For rapid iteration, run an ephemeral server. It starts with a clean state and a pre-configured debug user.

```bash
# Enable AI features for development
export SUPERNOTE_GEMINI_API_KEY="your_api_key"

# Start the ephemeral server
supernote serve --ephemeral
```

The server will print the temporary storage path and login command:
```bash
Created default user: debug@example.com / password
Run command to login:
  supernote cloud login --url http://127.0.0.1:8080 debug@example.com --password password
```

### AI Skills & Agentic Coding

This project includes "AI Skills" to help developers (and AI agents) interact with the codebase effectively. See `.agent/skills` for more details on how we structure these for automated development.

### Uploading Files

Test the sync flow using the CLI:

```bash
# Upload a test file
supernote cloud upload tests/testdata/20251207_221454.note
```
