# Design: Asynchronous Note Processing

This document outlines the architecture for evolving the Supernote Lite server into an intelligent knowledge base. It focuses on asynchronous, multi-stage processing of `.note` files.

## 1. Core Principles
- **Incremental & Page-Atomic**: The **Page** is the unit of processing. Only modified pages trigger expensive operations (OCR, Chunk Embeddings).
- **Hierarchical Knowledge**: Intelligence is captured at two levels: **Chunks** (individual pages) for granular search, and **Documents** (whole files) for summaries and global classification.
- **Asynchronous & Event-Driven**: Processing is triggered by events post-sync (`NoteUpdatedEvent`) and runs in the background using `asyncio`. Sync is never blocked.
- **Operation-Level Status Tracking**: Every stage (PNG, PDF, OCR, Embeddings) is tracked independently. The user can access the "Visual" content (PDF) immediately or while intelligence tasks (OCR) are still running or retrying with exponential backoff.
- **Personal-Scale Concurrency**: Optimized for household use (1-2 users). Uses an internal `asyncio.Queue` with limited concurrency to prevents resource exhaustion.
- **Privacy & Isolation**: OCR text and embeddings are stored and indexed strictly **per-user**.
- **Lifecycle Management**: Associated artifacts are purged when the source file is deleted.

4.  **Resilience & Recovery**: Intelligent tasks (OCR, Embeddings) include persistent state in the database. On server startup, the `ProcessorService` scans the `NotePageStatus` table for unfinished tasks and re-enqueues them.

## 3. Data Schema (Proposed)

### `NotePageStatus` (Table - Process Tracking)
Tracks the *state* of the pipeline. Not visible to the user.
- `file_id`, `page_index`, `content_hash`.
- `png_status`, `ocr_status`, `embed_status`.
- `retry_count`, `last_error`.

### `SummaryDO` (User-Facing Results)
We leverage the existing `SummaryService` to store our outputs.
1.  **"AI Insights" Summary**:
    - `uniqueIdentifier`: Derived from File UUID (e.g., `{uuid}-summary`).
    - `content`: The structured/formatted synthesis (Topics, Actions).
    - `metadata`: JSON blob with structure for UI parsing.
2.  **"OCR Transcript" Summary** (Optional/Configurable):
    - `uniqueIdentifier`: Derived from File UUID (e.g., `{uuid}-transcript`).
    - `content`: Full concatenated text of the note. Useful for portability.
    - `metadata`: `{"page_offsets": {1: 0, 2: 500...}}` to allow mapping search hits back to pages.

### `NotePageContent` (Internal Cache - Optional)
If we don't want to parse the large "Transcript Summary" every time we need a single page's text for a diff-update, we might keep a lightweight intermediate table:
- `file_id`, `page_index`, `raw_text`.
(Alternatively, we just re-read the Transcript Summary and splice it).

## 4. Pipeline Logic
1.  **Diff Phase**: Parser extracts page streams. Each stream is hashed and compared to the database.
2.  **Visual Phase**: Generate PNGs for new/changed pages. Assemble full PDF using cached PNGs for unchanged pages.
3.  **Intelligence Phase**:
    - Send PNG to Gemini (with retry/backoff) for OCR.
    - **Chunk Embeddings (Page-indexed)**: Generated per-page from raw OCR text. Ideal for "finding the needle in the haystack."
4.  **Document Phase**:
    - **Transcript Generation**: Aggregate all page text into a single "OCR Transcript" `SummaryDO`.
    - **Insight Generation**: Prompt Gemini with the transcript to create an "AI Insights" `SummaryDO`.
    - **Vector Indexing**:
        - **Chunks**: Generate vectors for each page window. Store in-memory index `(file_id, page_index)`.
        - **Document**: Generate vector for the Insight Summary. Store in-memory index `(file_id)`.

## 5. Intelligence API Surface

The API distinguishes between finding *where* something was said and *which* note is about a topic.

- **Semantic Search (Chunks)**: `GET /api/knowledge/search/chunks?q=...`
    - **Purpose**: "Find exactly where I wrote about X."
    - **Internals**: Queries the page-level vector index.
    - **Output**: Ranked list of page snippets and deep-links.
- **Semantic Search (Documents)**: `GET /api/knowledge/search/documents?q=...`
    - **Purpose**: "Which of my notebooks are about topic Y?"
    - **Internals**: Queries the document-level vector index (1 vector per file).
    - **Output**: Ranked list of notebooks with high-level summaries.
    - **Optimization**: Global searches use the Document index first for speed, then can drill down into Chunks within selected documents.
- **Document Summary**: `GET /api/file/{id}/summary`
    - Proxies to `SummaryService.list_summaries(..., type='AI_INSIGHT')`.
- **Processing Status**: `GET /api/knowledge/status/{file_id}`
    - Queries `NotePageStatus` table.

## 6. Cleanup
- On file deletion, `NoteDeletedEvent` triggers a purge of:
    - Blob storage artifacts (PNG/PDF).
    - Database entries (OCR text, status).
    - **Vectors**: Stored as per-user `(id, vector)` pairs in the database or sidecar files. Given the small scale (1-2 users), search is performed via **exhaustive in-memory vector comparison** (e.g., NumPy cosine similarity) to avoid heavy external dependencies.

### 8. Processor Module API Contract

Each stage of the pipeline is implemented as a `ProcessorModule`. The interaction between the orchestrator and modules follows a strict contract.

### Core Methods

| Method | Role | Return/Side Effect |
| :--- | :--- | :--- |
| `run_if_needed` | **Gating** | `True`: Run `process`. `False`: Skip. |
| `process` | **Work** | Main logic. Overwrites domain data (idempotent). |
| `run` | **Lifecycle** | Entry point. Manages `SystemTaskDO` status. |

### Return Value Semantics

*   **`run_if_needed` -> `False`**:
    *   **Meaning**: Task is either already `COMPLETED`, its prerequisites are missing (e.g., OCR needs PNG), or the feature is disabled (e.g., Gemini API key missing).
    *   **Result**: `run()` returns `True` immediately without calling `process()`. The pipeline continues as if this step was successful.
*   **`run` -> `True`**:
    *   **Meaning**: The step is successfully finished or was gracefully skipped. The orchestrator can proceed to the next module in the chain.
*   **`run` -> `False`**:
    *   **Meaning**: The step **FAILED** (exception raised during `process`). The orchestrator **stalls** the pipeline for this page/file. This prevents cascading errors and allows for retry on next trigger.

## 9. Failure & Exception Semantics

To maintain a resilient pipeline, modules must follow specific error handling patterns:

### 1. Expectations for `process()`
- **No Internal Try/Except (Mostly)**: Modules should let exceptions bubble up. The base class's `run()` method is the centralized error handler.
- **Descriptive Exceptions**: Raise specific exceptions (e.g., `FileNotFoundError`, `GeminiAPIError`) so the automated logs are useful.
- **Idempotency is Mandatory**: If `process()` fails halfway (e.g., after writing a file but before updating a DB record), the next attempt must be able to resume or overwrite without creating duplicates or corruption.

### 2. Orchestrator Reaction
- **Sequential Stall**: When a module returns `False` (Failure), the `ProcessorService` stops the sequential chain for that specific page.
    - Example: If `PNG_CONVERSION` fails, `OCR_EXTRACTION` is NOT attempted.
- **Persistent Error State**: The exception message is stored in `f_system_task.last_error`.
- **Automatic Retry**: Recovery logic on startup or subsequent file updates will re-attempt `FAILED` tasks.

### 3. Recoverable vs. Fatal Errors
- **Transient (Recoverable)**: Network timeouts, API rate limits. These should result in an exception that triggers a `FAILED` status, ready for retry.
- **Business/Logic (Fatal)**: Missing files that shouldn't be missing, or corrupted data. These also result in `FAILED`, but may require manual resolution (fixing the file) or code changes.

### Failure Modes & Corner Cases

1.  **Dependency Staleness**: If `PageHashingModule` detects a change, it deletes the `SystemTaskDO` entries for `OCR` and `Embedding`. This causes their `run_if_needed` to return `True` on the next run, forcing a re-poll.
2.  **Concurrency Limits**: `ProcessorService` limits the number of files processed in parallel. Modules should use internal semaphores (like `GeminiService`) if they have external API rate limits.
3.  **Idempotency Requirement**: If a task fails *after* writing data but *before* updating its status to `COMPLETED`, it will be re-run. `process()` must be safe to call again (e.g., using `UPSERT` or overwriting files).
