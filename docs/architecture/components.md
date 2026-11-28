# Server Component Catalog

`supernote.server` is organized around a concrete core host (`ServerCore`) and **25 lazy-loaded vertical components** under `supernote/server/components/`. Disabled components are never imported at startup, keeping bare sync deployments around ~135 MB of RAM while letting you opt into higher-level capabilities one domain at a time.

For lifecycle contracts, dependency resolution, and plugin rules, see [ADR 0001: ServerCore and Vertical Component Architecture](./adr/0001-server-core-component-architecture.md), [ADR 0003: Component Configuration and Runtime Reconfiguration Architecture](./adr/0003-component-configuration-architecture.md), [ADR 0004: Notebook Processing, Metadata, Conversion, and Transcript Component Ownership](./adr/0004-note-processing-component-ownership.md), and [Server & Sync Protocol Architecture](./server_architecture.md).

## Core host vs. optional components

Hardware sync and authentication stay concrete on `ServerCore` (`supernote/server/core.py`): SQLite session management, content-addressable blob storage, virtual file system (`FileService`), user accounts/JWT/API keys (`UserService`), TTL coordination, and the in-process event bus. Everything else lives in a vertical component registered in `BUILTIN_COMPONENTS` (`supernote/server/components/__init__.py`).

The `config` component resolves each built-in component's effective configuration across four priority tiers (`SUPERNOTE_*` environment variables `env` > explicit `config.yaml` `yaml` > persisted SQLite overrides `database` > component defaults `default`). Components marked `runtime_configurable=True` (such as `webhooks`) can be started, restarted, or stopped live via `ComponentLoader.async_reconfigure` without restarting the server.

## Built-in component catalog

| Domain | Default Enabled | Dependencies | Platforms | Responsibility |
| :--- | :---: | :--- | :--- | :--- |
| `ai` | Yes | — | `http` | AI provider registry (`ocr`, `summary`, `embedding`, `text`) and prompt/provider coordination. |
| `apple` | No | `ai` | `ocr` | macOS Vision (`vision-accurate` / `vision-fast`) offline OCR provider. |
| `config` | Yes | — | `http` | Server configuration normalization, runtime component reconfiguration, and admin config HTTP routes. |
| `conversion` | Yes | `ai`, `processor` | `http`, `mcp`, `processor` | `.note` and digest handwriting conversion to PDF, PNG, and SVG (`/api/file/*/to/*`), PNG caching, and `get_page_image` MCP tool. |
| `events` | Yes | — | `http`, `mcp` | Durable domain event log (`f_user_event`), retention pruning, and event inspection. |
| `fake_ai` | No | `ai` | `ocr`, `summary`, `embedding`, `text` | Deterministic in-memory AI provider for tests and ephemeral local runs. |
| `files` | Yes | — | `http`, `mcp` | Cloud file browsing, inline/presigned document uploads (`PUT /api/extended/uploads/{token}`), folder creation, and soft-delete MCP tools. |
| `gemini` | No | `ai` | `ocr`, `summary`, `embedding`, `text` | Google Gemini Vision, text, and embedding provider (auto-enabled when a Gemini key is configured). |
| `http` | Yes | — | — | Main-port `aiohttp` route registrar (`http` platform host). |
| `inbox` | Yes | — | — | Markdown-to-EPUB/PDF e-ink document builder for `/INBOX` reading material. |
| `integrity` | Yes | — | `http` | Two-way VFS, database, and disk blob integrity verification endpoints. |
| `mcp` | Yes | `oauth` | — | Streamable HTTP Model Context Protocol server (`mcp` platform host on port `8081`). |
| `metrics` | Yes | — | `http` | Prometheus `/metrics` endpoint and periodic storage metrics collector. |
| `note_metadata` | Yes | `processor` | `http`, `processor` | `.note` structure extraction (`NoteMetadataModule`), metadata API (`POST /api/extended/file/note/metadata`), and signed title crop previews (`GET /api/oss/title/*`). |
| `oauth` | Yes | — | `http` | OAuth 2.1 Authorization Server (PKCE, CIMD, consent UI, token issuance/revocation). |
| `openai` | No | `ai` | `ocr`, `summary`, `embedding`, `text` | OpenAI-compatible provider supporting OpenAI API, Ollama, vLLM, llama.cpp, and LM Studio. |
| `processor` | Yes | — | `http`, `processor` | Incremental background note/image processing queue and page hashing. |
| `schedule` | Yes | — | `http`, `mcp` | Supernote Tasks & Schedule CRUD, RFC 5545 `.ics` feed export, and 4 MCP task tools. |
| `search` | Yes | `ai` | `http`, `mcp`, `processor` | Lexical keyword search, vector embeddings, hybrid ranking, and `list_notebooks` / `search_notebook_chunks` MCP tools. |
| `socketio` | Yes | — | `http` | Real-time Socket.IO sync notifications (`FILE-SYN`, `TASK-SYN`, `SUMMARY-SYN`). |
| `summary` | Yes | `ai`, `conversion` | `http`, `processor` | Reading digests, AI notebook summaries, and cached digest handwriting PDF/PNG rendering. |
| `timeline` | Yes | `note_metadata`, `events` | `http` | Cross-notebook chronological page timeline (`POST /api/extended/timeline/pages` and `/days`) combining `<PAGEID>` creation dates, synced page edit deltas (`note.pages_delta`), and optional AI summary date/blurb enrichment. |
| `transcript` | Yes | `ai`, `conversion`, `note_metadata` | `http`, `mcp`, `processor` | OCR page transcription stage, transcript storage, and `get_notebook_transcript` MCP tool. |
| `web_ui` | Yes | — | `http` | Zero-build Vue 3 editorial Web UI served from `supernote/server/static/`. |
| `webhooks` | No | `events` | — | HMAC-SHA256 signed outbound HTTP webhooks (`note.sync_completed`, etc.). |
| `wiki` | No | `ai`, `events` | `http`, `mcp` | Opt-in LLM Wiki compiler, lint engine, Obsidian `.zip` export, and 8 MCP wiki tools. |

## Platform modules

Components extend shared surfaces declaratively via `platforms` (`KNOWN_PLATFORMS` in `supernote/server/components/__init__.py`). Each declared platform maps 1:1 to a `<platform>.py` module defining `async def async_setup_<platform>(core, registrar)`:

- `http`: Registers main-port HTTP routes and middlewares.
- `mcp`: Registers MCP tools onto `McpRegistrar`.
- `processor`: Registers background processing pipeline stages.
- `ocr`, `summary`, `embedding`, `text`: Registers AI model backends onto `ai`.

Conformance tests in `tests/server/components/test_init.py` verify that every package on disk matches `BUILTIN_COMPONENTS`, enforces declared-dependency import boundaries, and confirms disabled components are never imported.
