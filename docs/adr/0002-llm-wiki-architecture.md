# ADR 0002: Hybrid LLM Wiki Component Architecture

- **Status**: Proposed
- **Date**: 2026-11-23
- **Scope**: `supernote.server.components.wiki`, `ai` `"text"` platform, multi-user SQLite wiki storage (`f_wiki_*`), incremental event compilation, Obsidian Markdown export, MCP tools, Web UI, and evaluation gates

---

## 1. Context and Goals

Supernote users accumulate long-lived handwritten notebooks (`.note` files with per-page OCR transcripts in `NotePageContentDO`) alongside structured tasks (`ScheduleTaskDO`, often linked to notebook pages). Today, AI retrieval operates primarily via per-notebook chronological summaries (`SummaryModule` -> `SummaryDO` tablet digests) and chunk-level vector search (`SearchService`). While effective for single-notebook recaps and ad-hoc lookups, chunk retrieval re-derives cross-notebook connections on every query and struggles with evolving facts across months of notes and task updates.

This ADR defines a **Hybrid LLM Wiki** inspired by Andrej Karpathy's *"compile once, query cheaply"* knowledge-base pattern and grounded in `supernote.server`'s `PlatformHost` vertical component architecture ([ADR 0001](./0001-server-core-component-architecture.md)) and incremental diff event stream (`f_user_event`, PR #663):

1. **Hybrid runtime (built-in + external agents):** The server owns durable wiki storage, REST APIs, MCP tools, and Obsidian export. Compilation can run either via an opt-in in-process `WikiCompilerWorker` or via external agents polling `list_events` / `GET /api/extended/events` and writing back through the Wiki HTTP/MCP APIs with canonical actor attribution.
2. **Decoupled from `SummaryModule` and `VirtualFileSystem`:** Wiki compilation operates across notebooks and schedule tasks per user—never inside `ProcessorService`'s per-file lock, never writing to `SummaryDO` (tablet Digest sync/blob GC), and never materializing live `.md` files into `UserFileDO` (tablet VFS sync and storage quotas).
3. **Strict architectural conformance:** Every component file follows [`.agent/rules/component-architecture.md`](../../.agent/rules/component-architecture.md), every ORM table satisfies `tests/server/db/models/test_init.py` and `tests/server/db/test_migrations.py` with zero allowlist additions, and delivery proceeds in small (~150–280 LoC) independently shippable PRs.

---

## 2. Component Architecture & Platform Integration

### 2.1 Vertical Component Layout (`supernote/server/components/wiki/`)

`WikiComponent` is registered alphabetically in `BUILTIN_COMPONENTS` ([`supernote/server/components/__init__.py`](../../supernote/server/components/__init__.py)) with `default_enabled=False` so disabled deployments incur zero import or runtime cost. Because `http`, `mcp`, and `ai` are `PlatformHost` components orchestrated by `ComponentLoader.async_load_all_platforms`, `WikiComponent` requires no manual ordering tricks and zero edits to `components/mcp/`:

```python
class WikiComponent:
    domain = "wiki"
    dependencies: tuple[str, ...] = ("ai", "events")
    platforms: tuple[str, ...] = ("http", "mcp")
```

File roles follow the five rules in `.agent/rules/component-architecture.md` (enforced by `tests/server/components/test_init.py`):

| File | Responsibility |
| :--- | :--- |
| `__init__.py` | Lifecycle shell (`WikiComponent`: `async_setup`, `async_start`, `async_stop`) and re-export of `WIKI_SERVICE_KEY`. |
| `config.py` | Pure `mashumaro` `WikiConfig` dataclass (`enabled`, `auto_compile`, `debounce_seconds`, `max_pages_per_batch`, `daily_token_budget`, `lint_event_threshold`, `lint_interval_days`). |
| `models.py` | Pure `mashumaro` internal/MCP request & response models and canonical `WikiClaim` / `WikiCompilePlan` schemas. |
| `service.py` | Transport-free `WikiService` (CRUD, optimistic concurrency, revision snapshots, link/source indexing, pure-ORM hybrid search, zero-LLM structural lint) and component-owned `WIKI_SERVICE_KEY` (never added to `supernote/server/keys.py`). |
| `compiler.py` | `WikiCompilerWorker`: `DomainEventRecorded` wake-up, per-user debouncing, `EventLogService.list_events()` cursor catch-up, single async SQLite writer queue, backfill, and thresholded LLM lint. |
| `export.py` | `WikiExportService`: streaming Obsidian-compatible Markdown (`.md`) and `.zip` vault generation (modeled on `ICalExportService`). |
| `http.py` | `async_setup_http(core, registrar)`: `/api/extended/wiki/*` `aiohttp` route handlers. |
| `mcp.py` | `async_setup_mcp(core, registrar)`: registers wiki MCP tools onto `McpRegistrar` with automatic actor binding and Prometheus metrics. |

### 2.2 Provider-Neutral `"text"` AI Platform (`components/ai/`)

Existing `SummaryModel` is bound exclusively to `SummaryResponse` (date-grouped notebook segments). Rather than coupling wiki synthesis to `SummaryModel`, `AiComponent` ([`supernote/server/components/ai/__init__.py`](../../supernote/server/components/ai/__init__.py)) adds a fourth capability platform:

- **`AI_PLATFORMS = ("ocr", "summary", "embedding", "text")`** and **`KNOWN_PLATFORMS`** updated with `"text"`.
- **`TextGenerationModel` (`supernote/server/ai/models/text.py`)**: Provider-neutral interface (`generate_json(prompt, response_schema, *, stage) -> TextGenerationResult`) returning parsed JSON plus token usage, wrapped by `ConcurrencyLimitedTextModel` and `InstrumentedTextModel` (`AIStage.WIKI_COMPILE`, `AIStage.WIKI_LINT`).
- **Vendor registration**: `components/gemini/text.py`, `components/openai/text.py`, and `components/fake_ai/text.py` implement `async_setup_text(core, registrar)` calling `registrar.register_text(...)`.
- **Configuration**: `ServerConfig.ai.text: ModelConfig | None = None` (opt-in; zero surprise LLM calls for existing deployments).
- **Prompts**: `PromptLoader` adds `PromptId.WIKI_COMPILE`, `PromptId.WIKI_CONFLICT`, and `PromptId.WIKI_LINT` under `supernote/server/resources/prompts/`. Formatting helpers substitute `{{...}}` placeholders explicitly (never `str.format()`) and sanitize XML boundary tags inside untrusted note/task payloads.

---

## 3. Data Model, Multi-User Invariants & Storage Boundaries

### 3.1 Dedicated SQLite ORM Tables (`supernote/server/db/models/wiki.py`)

All wiki state lives in seven pure SQLAlchemy 2.0 ORM tables registered on `Base.metadata` via a linear Alembic migration chained off current head `c7d8e9f0a1b2` (`c7d8e9f0a1b2_add_oauth_grants_table.py`). Every table carries non-nullable `user_id` (`BigInteger`) in its **primary key** and in **every unique constraint and unique index**, satisfying `tests/server/db/models/test_init.py` with zero allowlist additions:

| Table (`*DO`) | Composite PK | Unique Constraints | Role |
| :--- | :--- | :--- | :--- |
| `f_wiki_page` (`WikiPageDO`) | `(user_id, page_id)` | `(user_id, slug)` | Current page state: `slug`, `title`, `page_kind`, `summary`, `body_md`, `claims_json`, `edit_policy`, `last_author_kind`, `version`, `is_deleted`, timestamps. Soft-deleted slugs are revived in place (`is_deleted=False`, incremented `version`) so revision history stays unified under one `page_id`. |
| `f_wiki_revision` (`WikiRevisionDO`) | `(user_id, revision_id)` | `(user_id, page_id, revision_no)` | Immutable snapshot & audit trail (`title`, `body_md`, `claims_json`, `author_kind`, `author_ref`, `change_summary`, `source_event_seq`, `create_time`). |
| `f_wiki_alias` (`WikiAliasDO`) | `(user_id, alias_id)` | `(user_id, normalized_alias)` | Canonical entity/slug alias map mitigating handwriting OCR typo fragmentation (`compiler \| user \| lint_approved`). |
| `f_wiki_link` (`WikiLinkDO`) | `(user_id, from_page_id, target_slug)` | *(PK)* | Directed `[[wikilink]]` edges (`target_page_id`, `link_label`) for $O(1)$ 1-hop traversal, backlinks, and zero-LLM broken-link / orphan detection. |
| `f_wiki_source_ref` (`WikiSourceRefDO`) | `(user_id, page_id, source_type, source_key)` | *(PK)* | Provenance links to `note_page` (`"{file_id}:{page_id}"`) and `schedule_task` (`"{task_id}"`), with `file_id`, `last_event_seq`, and `is_source_deleted`. |
| `f_wiki_checkpoint` (`WikiCheckpointDO`) | `(user_id,)` | *(PK)* | Per-user durable compile cursor (`last_sync_token`), lint counters (`pending_events_since_lint`, `last_lint_time`), backfill progress (`backfill_file_cursor`), daily token budget (`tokens_used_day`, `budget_day_utc`), `status`, `last_error`. |
| `f_wiki_lint_issue` (`WikiLintIssueDO`) | `(user_id, issue_id)` | `(user_id, dedup_key)` | Idempotent structural & semantic lint findings (`broken_link \| orphan_page \| stale_source \| contradiction \| alias_merge_proposal`) with `proposal_json` and `status` (`open \| resolved \| dismissed`). |

### 3.2 Storage Boundaries

- **No live VFS materialization:** Writing `.md` files into `UserFileDO` would pollute hardware tablet sync, trigger `Vfs*Event` feedback loops, inflate user storage quotas, and break `IntegrityService` checks. Instead, `WikiExportService` streams Obsidian-compatible `.md` files (with YAML frontmatter and `[[wikilinks]]`) and `.zip` vaults on demand via HTTP.
- **No raw `FTS5` virtual tables in the main DB (v1):** `tests/server/db/test_migrations.py` enforces `set(reflected.tables) - INTERNAL_TABLES_ALLOWLIST == set(Base.metadata.tables)`. SQLite `FTS5` virtual tables spawn shadow tables (`*_data`, `*_idx`, `*_docsize`, `*_config`, `*_content`) that break reflection equality. v1 uses pure-ORM lexical/alias scoring plus optional in-process NumPy cosine similarity (matching `SearchService`). If corpus scale later requires native `FTS5` / `sqlite-vec` (>10k pages/user), v2 isolates them in an auxiliary `<storage_dir>/wiki_index.sqlite` outside `Base.metadata`.
- **Account cleanup readiness:** `WikiService` exposes `delete_user_wiki(user_id)` so Phase 4 user-deletion hooks (`UserService.clear_account`) can cascade-delete all `f_wiki_*` rows cleanly.

---

## 4. Page Taxonomy, Event Spine & Incremental Compilation

### 4.1 Canonical Page Taxonomy

Slugs use a bounded, plural-prefixed namespace:

- `index` (`page_kind="index"`): Compact catalog of active pages (`slug`, `title`, 1-line summary, updated date) regenerated deterministically or bounded to top-$K$ entries in prompts.
- `log` (`page_kind="log"`): Append-only chronological compilation and lint log.
- `sources/<file_id>` (`page_kind="source_digest"`): Per-notebook provenance anchor linking exact `file_id:page_id` citations so renames (`VfsItemMovedEvent`) and deletes (`VfsItemDeletedEvent`) update one stable anchor.
- `projects/<slug>` (`page_kind="project"`): Cross-notebook initiatives and Schedule task lists.
- `entities/<slug>` (`page_kind="entity"`): People, organizations, and places (promoted only when evidenced across $\ge 2$ sources or a dedicated task list).
- `topics/<slug>` (`page_kind="topic"`): Recurring themes, decisions, and concepts.

### 4.2 Durable Event Spine & Per-User Serialization

`LocalEventBus.publish()` dispatches by exact `type(event)` match (no subclass dispatch), and non-inline handlers run as unordered `asyncio.create_task` jobs. `WikiCompilerWorker` therefore uses a two-layer durable design:

1. **Wake-up signal:** Subscribes (`inline=False`) to `DomainEventRecorded` (emitted by `EventLogService` *after* committing `f_user_event`), filtering for `note.page_transcribed`, `note.pages_delta`, `schedule.task_created`, `schedule.task_updated`, `schedule.task_deleted`, `vfs.moved`, and `vfs.deleted`, plus `VfsItemPurgedEvent` for permanent purges.
2. **Per-user debounce & cursor catch-up:** Coalesces events per `user_id` over a short debounce window (default `15s`) so multi-page tablet syncs compile as a single batch. On wake-up (and on server startup), the worker drains events from `EventLogService.list_events(user_id=..., sync_token=checkpoint.last_sync_token)` in ascending `seq` order, ensuring crash recovery and restart-safe replay. On `CursorExpiredError` (cursor older than the 90-day retention window), the worker pauses with a status warning and lets the user trigger an incremental backfill scan.
3. **Tenant-scoped enrichment & write serialization:**
   - When enriching `ScheduleTask*Event` (which omits `recurrence`, `importance`, `completed_time`, and linked page OCR text), queries `ScheduleTaskDO` filtered by `user_id` and `NotePageContentDO` **strictly joined to `UserFileDO` (`UserFileDO.user_id == user_id AND UserFileDO.is_active == "Y"`)** since `NotePageContentDO` has no `user_id` column.
   - All LLM HTTP calls run strictly **outside** open SQLite sessions; final multi-table commits serialize through a single async writer queue to eliminate WAL write contention.

### 4.3 Incremental Compilation, Conflict Resolution & OCR Hygiene

- **Bounded two-step compile:** Pass a capped compact index ($\le 100$ active/matched entries), candidate existing pages (resolved via `f_wiki_source_ref`, `f_wiki_alias`, and 1-hop `f_wiki_link`), and the PR #663 diff batch (`previous_text -> text_content`, `deleted_page_texts`, `changed_fields`). Cap fan-out to **$\le 5$ pages per batch** in Python (`WikiService`).
- **Bi-temporal non-destructive claims:** Rather than deleting contradicted facts, `claims_json` tracks `{claim_id, text, status: "active" | "superseded" | "retracted", valid_from, invalid_at, supersedes_claim_id, superseded_by_source, source_refs}`, and every mutation appends an immutable `WikiRevisionDO` snapshot.
- **Human/agent co-editing safety:**
  - Optimistic concurrency (`expected_version`) returns HTTP `409 Conflict` / MCP conflict error on stale writes.
  - `edit_policy`: compiler-created pages default to `"auto"`; any manual Web UI or MCP `upsert_wiki_page` edit flips the page to `"protected_prose"`, restricting the compiler to structured citations, an automated-notes appendix, or `f_wiki_lint_issue` proposals; `"locked"` blocks all compiler writes.
- **Handwriting OCR entity hygiene:** Minor unambiguous alias matches resolve via `f_wiki_alias`; ambiguous potential duplicates (e.g., OCR typo `Al1ce` vs `Alice`) are **never** silently auto-merged—they emit an `alias_merge_proposal` row in `f_wiki_lint_issue` for explicit human/agent approval.
- **Cost-controlled backfill & two-tier lint:**
  - *Backfill:* Opt-in (`POST /api/extended/wiki/compile` with `mode="backfill"`), newest-first in small chunks, checkpointed in `f_wiki_checkpoint.backfill_file_cursor`, bounded by `daily_token_budget`.
  - *Lint Tier A (Zero-LLM SQL, runs free after every compile):* Upserts broken links, orphan pages, deleted source refs, and fuzzy alias candidates idempotently into `f_wiki_lint_issue` by `(user_id, dedup_key)`.
  - *Lint Tier B (Bounded Sleep-Time LLM):* Runs only when `pending_events_since_lint >= lint_event_threshold` or `lint_interval_days` elapses and daily token budget remains.

---

## 5. Query, HTTP, MCP & Web UI Surfaces

### 5.1 Pure-ORM Hybrid Retrieval (v1)

`WikiService.search_wiki(user_id, query, top_k=10)` executes in four deterministic steps without LLM calls:
1. Lexical + alias scoring across `f_wiki_page` (`title`, `slug`, `summary`, `body_md`) and `f_wiki_alias` (`normalized_alias`).
2. Optional in-process NumPy cosine similarity over `f_wiki_page.embedding` when `EmbeddingModel` is configured.
3. Reciprocal Rank Fusion ($k=60$) with a minimum relevance cutoff.
4. **1-hop `f_wiki_link` expansion** plus **grounded source snippets** from `NotePageContentDO` (joined to `UserFileDO` by `user_id`) and `ScheduleTaskDO` via `f_wiki_source_ref`.

### 5.2 HTTP API (`components/wiki/http.py`)

Mounted under `/api/extended/wiki/*` (protected by `jwt_auth_middleware` with automatic canonical `REQUEST_ACTOR_KEY` binding):
- `GET /api/extended/wiki/pages` — list/filter pages (`page_kind`, `limit`, `offset`)
- `GET /api/extended/wiki/pages/{slug:.+}` — read page, backlinks, and source refs
- `PUT /api/extended/wiki/pages/{slug:.+}` — create/update page (`expected_version`, optimistic `409`; revives soft-deleted tombstones in place)
- `DELETE /api/extended/wiki/pages/{slug:.+}` — soft-delete page
- `GET /api/extended/wiki/revisions/{slug:.+}` — list immutable revision history
- `GET /api/extended/wiki/search` — pure-ORM hybrid search + 1-hop links + grounded snippets
- `GET /api/extended/wiki/status` — checkpoint cursor, budget usage, lint counts
- `POST /api/extended/wiki/compile` — trigger `mode: "incremental" | "backfill" | "lint"`
- `GET /api/extended/wiki/lint` & `POST /api/extended/wiki/lint/{issue_id}/resolve` — inspect and resolve/dismiss lint proposals
- `GET /api/extended/wiki/export.zip` & `GET /api/extended/wiki/export/{slug:.+}.md` — streaming Obsidian vault / single-page Markdown export

### 5.3 MCP Tools (`components/wiki/mcp.py`)

Registered onto `McpRegistrar` via `registrar.add_tool(...)` (automatic `bind_event_actor` + dynamic Prometheus metrics; **tools-only in v1** with zero modifications to `components/mcp/`):
- `get_wiki_index`, `list_wiki_pages`, `read_wiki_page`, `search_wiki`, `upsert_wiki_page`, `list_wiki_lint_issues`, `resolve_wiki_lint_issue`, `get_wiki_status`.
- Pairs directly with the existing `list_events` MCP tool (`components/events/mcp.py`, supporting `exclude_actors=["self"]` echo suppression) so external agents can run a complete compile-and-query loop over MCP.
- Fine-grained `wiki:read` / `wiki:write` OAuth scopes (`components/oauth/models.py`) and `wiki://` MCP resources (`McpRegistrar.add_resource`) are deferred cleanly to v2.

### 5.4 Web UI (`supernote/server/static/`)

- Top-level **Wiki** tab (`#/wiki`, `#/wiki/<slug>`) in `index.html` and `useRouter.js`.
- Wikilink-aware wrapper around `js/utils/markdown.js` (`marked` + `DOMPurify`): renders `[[slug]]` / `[[slug|label]]` as in-app `#/wiki/<slug>` navigation links and preserves internal `#/file/<id>?page=<n>` citations without forcing `target="_blank"`, keeping `DOMPurify` XSS protections intact.
- Parallel `searchWiki` branch in `SearchModal.js`, worker/backfill status in `SettingsPanel.js` / `SystemPanel.js`, and real-time `WikiUpdatedEvent` sync over Socket.IO.

---

## 6. Evaluation Plan & Observability

To avoid the standard RAG evaluation traps (groundedness-without-temporal-truth, self-family LLM-judge bias, and single-metric Goodharting), wiki quality is gated across four tiers:

| Tier | Cadence & Cost | What It Verifies |
| :--- | :--- | :--- |
| **Tier 1: Deterministic CI Gate** | Every PR (<5s, \$0 LLM) | `test_init.py` / `test_migrations.py` conformance (0 allowlist edits), 0% broken wikilinks (paired with outgoing link density), 0% unreachable pages (paired with `index` size), 100% valid `f_wiki_source_ref`s, deterministic event-replay idempotency, and Obsidian `.zip` round-trip parsing. |
| **Tier 2: Synthetic Wiki Delta Benchmark (`SWDB`)** | Pre-merge / prompt changes | Scripted `NotePageTranscribedEvent` + `NotePagesDeltaEvent` + `ScheduleTask*Event` streams measuring **Stale-Fact Rate** (paired with historical retention), deleted-page/task retraction accuracy, unanswerable abstention, and OCR-typo entity resolution (B-Cubed F1). |
| **Tier 3: Factuality & Multi-Hop QA** | Nightly / release | Cross-family or compact NLI (`MiniCheck-770M`) claim groundedness, paired citation precision/recall, and 2–4 hop cross-note + schedule QA. |
| **Tier 4: Cost/Latency Pareto & Telemetry** | Nightly + live Prometheus | Head-to-head comparison of **Wiki lookup** vs. **`SearchService` vector RAG** vs. **full transcript scan** across query-to-compile ratios $Q/C \in \{0.1, 1, 5, 20\}$, tracked live via `AIStage.WIKI_COMPILE` / `AIStage.WIKI_LINT` metrics. |

---

## 7. Incremental PR Roadmap

Each slice targets ~150–280 LoC of production code on its own branch off `origin/main` with 1:1 mirror tests (`tests/test_init.py`) and zero forward dependencies:

| PR | Scope | Independent Verification Gate |
| :--- | :--- | :--- |
| **PR 1: ORM Models & Alembic Migration** | `supernote/server/db/models/wiki.py` (7 `*DO` models), `db/models/__init__.py`, Alembic migration chained off `c7d8e9f0a1b2`. | `pytest tests/server/db/models/test_init.py tests/server/db/test_migrations.py` passes with 0 allowlist changes. |
| **PR 2: `"text"` AI Platform & PromptLoader** | `supernote/server/ai/models/text.py`, `AiRegistrar.register_text` / `AI_PLATFORMS`, `components/{gemini,openai,fake_ai}/text.py`, `ServerConfig.ai.text`, `PromptId.WIKI_*`, `AIStage.WIKI_*`. | Unit tests with `FakeTextGenerationModel`, `ComponentLoader` platform tests, Prometheus metric checks. |
| **PR 3: `WikiService`, `WikiExportService` & `WikiComponent` Shell** | `components/wiki/{__init__,config,models,service,export}.py`, `BUILTIN_COMPONENTS` (`default_enabled=False`). | Multi-user isolation, optimistic `409`, pure-ORM search + 1-hop links, zero-LLM lint, `.zip` export, `tests/server/components/test_init.py`. |
| **PR 4: `WikiCompilerWorker`** | `components/wiki/compiler.py`: `DomainEventRecorded` wake-up, `EventLogService` cursor, 15s debounce, tenant-scoped enrichment, serialized writer queue, backfill & lint triggers. | Tier 1 deterministic replay tests + `SWDB` delta/conflict tests with mocked/recorded LLM. |
| **PR 5: HTTP & MCP Platforms** | `components/wiki/http.py`, `components/wiki/mcp.py`, `supernote/models/wiki.py` shared wire DTOs/VOs. | HTTP auth/conflict/export integration tests + MCP Streamable HTTP tool tests (`exclude_actors=["self"]`). |
| **PR 6: Vue 3 Web UI** | `#/wiki` tab (`index.html`, `useRouter.js`, `js/components/wiki/*`), wikilink-safe `markdown.js`, `SearchModal.js`, `SettingsPanel.js` / `SystemPanel.js`. | Frontend unit tests + headless Playwright visual & XSS verification (`server-ui` skill). |

### Explicit v2+ Deferrals
- Auxiliary `wiki_index.sqlite` (`FTS5` + `sqlite-vec`) if per-user corpus exceeds ~10k pages.
- Fine-grained `wiki:read` / `wiki:write` OAuth scopes in `components/oauth/` and `McpRegistrar.add_resource` (`wiki://index`, `wiki://pages/{+slug}`).
- Bidirectional Obsidian CLI/WebDAV sync, `SummaryUpsertedEvent` / PDF document ingestion, and interactive graph canvas UI.

### Key Research References
- Andrej Karpathy, *LLM Wiki* (Apr 2026) — three-layer `raw/` -> `wiki/` + `index`/`log` pattern.
- Lin et al., *Sleep-time Compute* (`arXiv:2504.13171`) — async background consolidation & test-time compute savings.
- Rasmussen et al., *Zep: A Temporal Knowledge Graph Architecture for Agent Memory* (`arXiv:2501.13956`) — bi-temporal claim invalidation.
- Guo et al., *LightRAG* (`arXiv:2410.05779`) & Gutiérrez et al., *HippoRAG 2* (`arXiv:2502.14802`) — incremental edge updates and passage-grounded graph retrieval.
- Zhang et al., *OHRBench: OCR Hinders RAG* (`arXiv:2412.02592`) — OCR semantic noise and conservative entity resolution.
- Wu et al., *LongMemEval* (`arXiv:2410.10813`), Hu et al., *MemoryAgentBench* (`arXiv:2507.05257`), Tang et al., *MiniCheck* (`arXiv:2404.10774`), and Anthropic, *Contextual Retrieval* — temporal update, abstention, grounding, and retrieval Pareto evaluation.
