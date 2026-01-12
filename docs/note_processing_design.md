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

## 7. Ongoing Research
1.  **Stable Page Hashing**: Determining the most reliable way to calculate the hash of a page's stroke data from the `.note` parser.
2.  **Summary Specification**: Revisit the specific schema and implementation for the hierarchical summary after the initial design has been fleshed out.
