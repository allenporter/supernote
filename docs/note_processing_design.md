# Asynchronous Note Processing Architecture

This document describes the architecture of the asynchronous, multi-stage `.note` processing pipeline implemented in `supernote.server.services.processor`.

---

## 1. Core Principles

- **Incremental & Page-Atomic**: The **Page** (identified by its stable `.note` `PAGEID`) is the unit of processing. Only modified or newly added pages trigger expensive operations (PNG rendering, LLM OCR, and vector embedding generation).
- **Blank Page Short-Circuiting**: `PageHashingModule` inspects each changed page's foreground layers (`has_drawables`). Blank pages (`has_drawables == False`) skip the OCR LLM call, vector embedding generation, and summary synthesis automatically.
- **Hierarchical Knowledge**: Intelligence is captured at three levels:
  1. **Binary Structural Metadata** (`NoteMetadataDO` and `NotePageMetadataDO`) for native `.note` headers, `PAGESTYLE` templates, keywords (`PAGE_KEYWORDS`), titles (`PAGE_TITLES`), links (`PAGE_LINKS`), and ink presence.
  2. **Page Chunks** (`NotePageContentDO`) for OCR transcripts and granular semantic vector search.
  3. **Documents** (`SummaryDO`) for full-notebook transcripts and chronological AI syntheses.
- **Asynchronous & Event-Driven**: Processing is triggered by domain events on `LocalEventBus` (`NoteUpdatedEvent`, `SyncCompletedEvent`) and runs in background `asyncio` workers. Device sync is never blocked. During active hardware sync sessions (`defer_processing=True`), processing is deferred until `SyncCompletedEvent` fires.
- **Operation-Level Checkpoints**: Every stage (`HASHING`, `PNG_CONVERSION`, `OCR_EXTRACTION`, `EMBEDDING_GENERATION`, `SUMMARY_GENERATION`) is tracked independently in `SystemTaskDO` (`f_system_task`), including module/model version tags (`SystemTaskDO.data`).
- **Personal-Scale Concurrency**: Uses a bounded `asyncio.Queue` of file IDs with configurable file worker concurrency (`concurrency=2`) and per-page semaphore concurrency (`DEFAULT_PAGE_CONCURRENCY`).
- **Privacy & Multi-User Isolation**: All metadata, OCR transcripts, vector embeddings, tasks, and summaries are scoped strictly per user (`user_id` composite primary keys).
- **Lifecycle & Garbage Collection**: When a `.note` file is deleted (`NoteDeletedEvent`), `ProcessorService` purges all associated `NoteMetadataDO`, `NotePageMetadataDO`, `NotePageContentDO`, `SystemTaskDO`, and `SummaryDO` rows, as well as cached page PNGs in `CACHE_BUCKET` and unreferenced handwriting blobs in `USER_DATA_BUCKET`.
- **Resilience & Self-Healing Recovery**: On server startup and every 5 minutes in `poll_loop()`, `ProcessorService` runs `recover_tasks()`, `recover_stalled_tasks()`, and `recover_missing_tasks()` to re-enqueue unfinished, stalled, or newly discovered/version-upgraded tasks.

---

## 2. Pipeline Architecture

```mermaid
flowchart TD
    EVT["NoteUpdatedEvent / SyncCompletedEvent"] --> Q["ProcessorService Queue\n(file_id)"]
    Q --> PRE["1. Global Pre-Processing\nPageHashingModule (HASHING, key='global', version='v2')\nUpserts NoteMetadataDO, NotePageMetadataDO & NotePageContentDO"]
    PRE --> DIFF{"Page Changed\nor New?"}
    DIFF -- "Unchanged" --> SKIP["Keep COMPLETED SystemTaskDO\n& Reuse Cached has_ink / has_drawables"]
    DIFF -- "Changed / New" --> INV["Invalidate Page SystemTaskDOs\n& SUMMARY_GENERATION Checkpoint"]
    INV --> PAGE_PAR["2. Per-Page Pipeline (Semaphore Throttled)\nkey='page_{page_id}'"]
    SKIP --> PAGE_PAR

    subgraph PageStage["Sequential Per-Page Modules"]
        PNG["PngConversionModule\n(PNG_CONVERSION -> CACHE_BUCKET)"]
        BLANK{"has_drawables\n== False?"}
        OCR_SKIP["Set text_content = ''\n(Skip LLM Call)"]
        OCR["OcrModule\n(OCR_EXTRACTION -> NotePageContentDO.text_content)"]
        EMB["EmbeddingModule\n(EMBEDDING_GENERATION -> NotePageContentDO.embedding\nSkips if is_blank)"]
        PNG --> BLANK
        BLANK -- "Yes (Blank)" --> OCR_SKIP --> EMB
        BLANK -- "No (Has Ink/Text)" --> OCR --> EMB
    end

    PAGE_PAR --> PageStage
    PageStage --> POST["3. Global Post-Processing\nSummaryModule (SUMMARY_GENERATION, key='global')\nUpserts OCR Transcript & AI Synthesis SummaryDO"]
    POST --> DONE["Publish NoteProcessingCompletedEvent"]
```

---

## 3. Data Schema (`supernote.server.db.models`)

### `SystemTaskDO` (`f_system_task` — Pipeline Checkpoint & Error Tracking)

Tracks the execution state of every module per user, file, and page (`supernote/server/db/models/note_processing.py`):

| Column | Type | Description |
| :--- | :--- | :--- |
| `user_id` | `BigInteger` (PK) | Owner user ID (`users.id`). |
| `id` | `BigInteger` (PK) | Internal task ID within user scope. |
| `file_id` | `BigInteger` | Numeric VFS file ID (`UserFileDO.id`). |
| `task_type` | `String` | `TaskType` value: `HASHING`, `PNG_CONVERSION`, `OCR_EXTRACTION`, `EMBEDDING_GENERATION`, or `SUMMARY_GENERATION`. |
| `key` | `String` | `"global"` for file-level modules (`PageHashingModule`, `SummaryModule`) or `"page_{page_id}"` for page-level modules. |
| `status` | `String` | `ProcessingStatus`: `PENDING`, `PROCESSING`, `COMPLETED`, or `FAILED`. |
| `data` | `Text` (nullable) | Module version or AI model identifier (e.g., `"v2"` for `PageHashingModule` and `PngConversionModule`, `embedding_model.model_id` for `EmbeddingModule`). |
| `retry_count` | `BigInteger` | Number of execution retries. |
| `last_error` | `Text` (nullable) | Exception type and message from the most recent failure. |
| `create_time` / `update_time` | `BigInteger` | Epoch timestamps in milliseconds. |

A `UniqueConstraint("user_id", "file_id", "task_type", "key")` ensures each stage has at most one checkpoint record per target.

### `NoteMetadataDO` (`f_note_metadata` — Notebook Header & Footer Cache)

Persisted by `PageHashingModule` (`version="v2"`) to expose parsed `.note` header/footer fields without re-reading the binary blob:

| Column | Type | Description |
| :--- | :--- | :--- |
| `user_id` | `BigInteger` (PK) | Owner user ID. |
| `file_id` | `BigInteger` (PK) | Numeric VFS file ID (`UserFileDO.id`). |
| `native_file_id` | `String` (nullable) | Device-generated `FILE_ID` from the `.note` header. |
| `file_type` | `String` (nullable) | Header `MODULE_LABEL` (`FILE_TYPE`, e.g. `"NOTE"`). |
| `signature` | `String` (nullable) | Format version signature (e.g. `"SN_FILE_VER_20230015"`). |
| `total_pages` | `Integer` | Total page count in the notebook. |
| `header_json` | `Text` | Full `NotebookMetadata.header` dictionary serialized as JSON. |
| `footer_json` | `Text` | Non-page footer entries (`COVER_*`, `STYLE_*`, ` dirtied`, etc.) serialized as JSON. |
| `create_time` / `update_time` | `BigInteger` | Epoch timestamps in milliseconds. |

### `NotePageMetadataDO` (`f_note_page_metadata` — Per-Page Structural & Ink Metadata)

Stores per-page structural metadata, ink/drawable flags, and native `.note` annotations across `0..total_pages - 1`:

| Column | Type | Description |
| :--- | :--- | :--- |
| `user_id` | `BigInteger` (PK) | Owner user ID. |
| `file_id` | `BigInteger` (PK) | Numeric VFS file ID (`UserFileDO.id`). |
| `page_index` | `Integer` (PK) | 0-based page order within the notebook. |
| `page_id` | `String` (nullable) | Stable `PAGEID` from the `.note` binary metadata. |
| `content_hash` | `String` (nullable) | MD5 hash of the page's metadata dictionary (used to skip re-scanning unchanged layer streams). |
| `page_style` | `String` (nullable) | Raw `PAGESTYLE` template identifier (e.g. `"style_h_8mm_ruled_line_a5x2"`, `"user_Daily"`). |
| `has_ink` | `Boolean` | `True` when `MAINLAYER` or `BGLAYER` contains vector strokes (`TOTALPATH`) or non-empty bitmap content (`page_has_ink`). |
| `has_drawables` | `Boolean` | `True` when the page has foreground strokes/bitmaps (`MAINLAYER` or `LAYER1..3`), a `TEXTBOX`, or `GARBAGE` vector shapes (`page_has_drawables`). `False` indicates a blank page. |
| `page_json` | `Text` | Full `PageMetadata` dictionary serialized as JSON. |
| `keywords_json` | `Text` | JSON list of footer `KEYWORD_*` dictionaries matching this page (`keyword_texts` property returns deduplicated keyword strings). |
| `titles_json` | `Text` | JSON list of footer `TITLE_*` heading dictionaries matching this page. |
| `links_json` | `Text` | JSON list of footer `LINK_*` hyperlink dictionaries matching this page. |

### `NotePageContentDO` (`f_note_page_content` — Page Text & Vector Cache)

Stores per-page change hashes, extracted OCR text, and vector embeddings:

| Column | Type | Description |
| :--- | :--- | :--- |
| `user_id` | `BigInteger` (PK) | Owner user ID. |
| `id` | `BigInteger` (PK) | Internal database ID within user scope. |
| `file_id` | `BigInteger` | Numeric VFS file ID (`UserFileDO.id`). |
| `page_index` | `BigInteger` | Current 0-based page order within the notebook. |
| `page_id` | `String` | Stable `PAGEID` from the `.note` binary metadata (`uq_note_page_content` with `user_id, file_id`). |
| `content_hash` | `String` (nullable) | MD5 hash of the page's metadata dictionary (layer offsets and protocol info). |
| `text_content` | `Text` (nullable) | Extracted OCR markdown/text for this page (`""` when skipped as a blank page). Property `is_blank` returns `True` when `text_content` is empty or whitespace-only. |
| `embedding` | `Text` (nullable) | JSON array of floats representing the page's vector embedding. |
| `embedding_model` | `String` (nullable) | Model ID that generated `embedding` (e.g. `gemini-embedding-001`). |

### `SummaryDO` (`f_summary` — User-Facing Transcripts & AI Synthesis)

`SummaryModule` persists document-level outputs via `SummaryService` into `f_summary` under a parent Summary Group (`is_summary_group=True`, `unique_identifier=get_summary_group_id(file_basis)`):

1. **OCR Transcript Summary**:
   - `unique_identifier`: `get_transcript_id(file_basis)`
   - `data_source`: `"OCR"`
   - `content`: Full concatenated transcript of all non-blank pages in the notebook, with page headers (including `Page Keywords:` when present) and inferred dates.
2. **AI Synthesis Summary**:
   - `unique_identifier`: `get_summary_id(file_basis)`
   - `data_source`: `summary_model.model_id`
   - `content`: Chronological Markdown synthesis with date-range headings and page citations (e.g., `## 2026-06-18 (Pages 1, 2)`).
   - `extra_metadata`: JSON object containing structured `segments` (`date_range`, `summary`, `extracted_dates`, `page_refs`).

---

## 4. Pipeline Stages (`supernote.server.services.processor_modules`)

1. **`PageHashingModule` (`TaskType.PAGE_HASHING`, Global Pre-Module, `version="v2"`)**:
   - Parses `.note` metadata once via `supernote.notebook.parse_metadata` and inspects existing `NotePageMetadataDO` rows.
   - For pages whose `content_hash` matches the existing `NotePageMetadataDO` row, reuses the cached `(has_ink, has_drawables)` flags without re-decoding binary layer streams. For new or modified pages, calls `supernote.notebook.load(stream, metadata=metadata, policy="loose", page_number=i)` in a worker thread to compute `page_has_ink` and `page_has_drawables`.
   - Upserts `NoteMetadataDO` (`f_note_metadata`) and `NotePageMetadataDO` (`f_note_page_metadata`, including `page_style`, `keywords_json`, `titles_json`, `links_json`).
   - Compares each page's `PAGEID` and `content_hash` against `NotePageContentDO`:
     - **New page**: Inserts a `NotePageContentDO` row.
     - **Moved page**: Updates `page_index` in place without re-running OCR/Embeddings if `content_hash` is unchanged.
     - **Modified page**: Updates `content_hash`, clears `text_content` and `embedding`, and deletes the page's `SystemTaskDO` rows (`key="page_{page_id}"`) so downstream page modules re-run.
     - **Deleted page**: Deletes the `NotePageContentDO` row, removes the cached PNG from `CACHE_BUCKET`, and deletes associated `SystemTaskDO` rows.
   - If any page was added, moved, modified, or deleted, deletes the `SUMMARY_GENERATION` `SystemTaskDO` checkpoint so `SummaryModule` regenerates the document transcript and synthesis.
2. **`PngConversionModule` (`TaskType.PNG_CONVERSION`, Page Module, `version="v2"`)**:
   - Uses single-page lazy loading (`load_notebook(path, policy="loose", page_number=page_index)`) and `ImageConverter` to render the page to PNG (`compress_level=1`) and stores it in `CACHE_BUCKET` at `get_page_png_path(file_id, page_id)`.
3. **`OcrModule` (`TaskType.OCR_EXTRACTION`, Page Module)**:
   - Checks `NotePageMetadataDO.has_drawables` first: if `has_drawables is False` (blank page), `run_if_needed()` does not require a cached PNG, and `process()` immediately sets `NotePageContentDO.text_content = ""` without invoking the OCR LLM.
   - For non-blank pages, verifies that `ocr_model` is configured and the page PNG exists in `CACHE_BUCKET`.
   - Loads `NotePageMetadataDO` (`page_style` and `keyword_texts`) into `supernote.server.utils.note_content.PageMetadata` and formats the prompt via `supernote.server.ai.prompts.format_ocr_prompt`:
     - **Prompt Routing Precedence**: Resolves custom prompts in `prompts_dir` (`supernote.server.utils.prompt_loader.PromptLoader`) by checking `file_name_basis` (lowercase notebook stem, e.g. `Daily.note` -> `daily`) -> `page_style_basis` (`normalize_page_style_type`, e.g. `user_Daily` -> `daily`, `style_h_8mm_ruled_line_a5x2` -> `8mm_ruled_line`) -> `default`.
     - **Page Keywords Injection**: Injects `Page Keywords: <kw1>, <kw2>` into the page metadata header block when native `.note` keywords exist on the page.
   - Calls `ocr_model.extract_text(png_data, prompt)` and stores the Markdown transcript in `NotePageContentDO.text_content`.
4. **`EmbeddingModule` (`TaskType.EMBEDDING_GENERATION`, Page Module)**:
   - Skips blank pages (`content.is_blank`).
   - For non-blank pages, calls `embedding_model.embed(text_content, task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT)` and stores the vector JSON and `model_id` in `NotePageContentDO`.
5. **`SummaryModule` (`TaskType.SUMMARY_GENERATION`, Global Post-Module)**:
   - Verifies that `summary_model` is configured and every page in `NotePageContentDO` for `file_id` has completed OCR (`text_content is not None`).
   - Filters out blank pages (`not p.is_blank`), formats each non-blank page with `format_page_metadata` (including `Page Keywords:`), and upserts the parent Summary Group, the full `"OCR"` transcript `SummaryDO`, and the segmented AI synthesis `SummaryDO` (skipping the LLM call if all pages in the notebook are blank).

---

## 5. Rapid Logging Markdown Parser (`supernote.server.utils.rapid_log`)

The built-in OCR prompts (`supernote/server/resources/prompts/ocr/`) transcribe handwritten Bullet Journal / Rapid Logging syntax into structured Markdown signifiers. `supernote.server.utils.rapid_log.parse_rapid_log` parses these OCR transcripts into typed `RapidLogItem` hierarchies for downstream task extraction and analysis:

| Signifier Syntax | `RapidLogKind` | `RapidLogTaskState` | Modifiers |
| :--- | :--- | :--- | :--- |
| `• ` (or `*• `) | `TASK` | `INCOMPLETE` | `starred=True` when prefixed with `*`; `strikethrough=True` when wrapped in `~~...~~` |
| `X ` (or `*X `) | `TASK` | `COMPLETED` | `starred` / `strikethrough` |
| `> ` (or `*> `) | `TASK` | `MIGRATED_FORWARD` | `starred` / `strikethrough` |
| `< ` (or `*< `) | `TASK` | `MIGRATED_SCHEDULED` | `starred` / `strikethrough` |
| `~~• ...~~` | `TASK` | `CANCELLED` | `strikethrough=True` |
| `O ` (or `*O `) | `EVENT` | `None` | `starred` / `strikethrough` |
| `- ` (or `*- `) | `NOTE` | `None` | `starred` / `strikethrough` |

Indented lines under a top-level bullet are attached as nested `children` (`RapidLogItem`) or `details` (`list[str]`), while `--- Page N ---` headers and metadata lines (`Notebook:`, `Created:`, `Page ID:`, `Page Keywords:`) are ignored automatically.

---

## 6. Extended Intelligence & Admin API Surface

### Extended Web & SDK Endpoints (`supernote.server.routes.extended` / `ExtendedClient`)

- **Semantic Search**: `POST /api/extended/search` (`ExtendedClient.search`)
  - Embeds the query with `EmbeddingTaskType.RETRIEVAL_QUERY` and performs in-memory NumPy cosine similarity across the user's `NotePageContentDO` vectors (`SearchService.search_chunks`), supporting `top_n`, `name_filter`, `date_after`, and `date_before`.
- **Notebook Transcript**: `POST /api/extended/transcript` (`ExtendedClient.get_transcript`)
  - Returns the formatted OCR transcript for an entire notebook or a specific `[start_index, end_index]` page range.
- **File Summaries**: `POST /api/extended/file/summary/list` (`ExtendedClient.list_summaries`)
  - Lists the `OCR` transcript and AI synthesis `SummaryDO` records for a `file_id`.
- **File Processing Status**: `POST /api/extended/file/processing/status` (`ExtendedClient.get_processing_status`)
  - Aggregates `SystemTaskDO` states for a list of `file_ids`.
- **Recent System Tasks**: `GET /api/extended/system/tasks` (`ExtendedClient.list_system_tasks`)
  - Returns recent `SystemTaskDO` entries for the authenticated user.
- **Domain Event Feed**: `GET /api/extended/events`
  - Queries per-user domain events (`EventLogService.list_events`) after `cursor` with optional `types`, `file_id`, `exclude_actor`, and `limit` filters.
- **Static API Keys**: `POST /api/extended/keys`, `GET /api/extended/keys`, `DELETE /api/extended/keys/{id}`
  - Creates, lists, and revokes `sn_...` Bearer API keys (`@interactive_session_only`).

### Admin Inspection & Recovery Endpoints (`supernote.server.routes.admin` / `AdminClient`)

- `GET /api/admin/queue/status`, `POST /api/admin/queue/stop`, `POST /api/admin/queue/start` — Inspect, pause, or resume `ProcessorService`.
- `GET /api/admin/tasks` — Filter `SystemTaskDO` records across the server by `status`, `file_id`, `task_type`, and `limit`.
- `POST /api/admin/reprocess` — Delete `SystemTaskDO` checkpoints for `all` or a specific `TaskType` (`hashing`, `png`, `ocr`, `embedding`, `summary`) and re-enqueue affected files.
- `POST /api/admin/users/quota` — Set a user's storage quota in bytes (`supernote admin user set-quota`).

---

## 7. ProcessorModule API Contract

Each stage inherits from `supernote.server.services.processor_modules.ProcessorModule`:

| Method | Role | Return / Side Effect |
| :--- | :--- | :--- |
| `run_if_needed(file_id, session_manager, page_index, page_id)` | **Gating** | `True`: Execute `process()`. `False`: Skip execution (already `COMPLETED` with matching `version`, module disabled, blank page, or prerequisite missing). |
| `process(file_id, session_manager, page_index, page_id)` | **Work** | Performs idempotent CPU/IO work and commits domain data updates. Raises descriptive exceptions on error. |
| `run(file_id, session_manager, page_index, page_id)` | **Lifecycle** | Calls `run_if_needed()`; if needed, runs `process()`, records Prometheus metrics, and updates `SystemTaskDO` to `COMPLETED` (with `data=self.version`) or `FAILED` (with `last_error` and incremented `retry_count`). |

### Failure & Stall Semantics

- **`run_if_needed() -> False`**: `run()` returns `True` immediately without calling `process()`, allowing the orchestrator to continue.
- **`run() -> False` (Exception in `process()`)**:
  - `SystemTaskDO.status` is set to `FAILED` with `last_error = f"{type(e).__name__}: {e}"`.
  - For page modules, `ProcessorService._process_page` **stalls** the sequential chain for that specific page (e.g., if `PngConversionModule` fails on page 2, `OcrModule` and `EmbeddingModule` are skipped for page 2, while other pages continue processing in parallel).
  - Stalled or failed tasks are automatically retried by `recover_stalled_tasks()` (after 5 minutes) or on demand via `supernote admin reprocess`.
