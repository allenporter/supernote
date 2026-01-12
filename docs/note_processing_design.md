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

### `NotePageStatus` (Table)
Tracks the status of individual operations per page.
- `file_id`: Reference to the user file.
- `page_index`: Integer.
- `content_hash`: Hash of the page's raw stroke data to detect changes.
- `png_status`: `DONE`, `FAILED`, `PENDING`.
- `ocr_status`: `DONE`, `FAILED`, `PENDING`.
- `embed_status`: `DONE`, `FAILED`, `PENDING`.
- `retry_count`: State for exponential backoff on intelligent tasks.

### `NoteKnowledge` (Table - Chunks)
Stores per-page intelligence.
- `file_id`: Reference.
- `page_index`: Integer.
- `ocr_text`: Raw extracted text.
- `chunk_embedding`: (Reference/Index) for granular search.

### `NoteDocumentKnowledge` (Table - Documents)
Stores whole-note intelligence.
- `file_id`: Reference.
- `summary_content`: Structured JSON (Overview, Actions, etc.).
- **Chunk Embeddings (Page-indexed)**: Generated per-page from raw OCR text. These are high-resolution vectors used for "finding the needle in the haystack."
- **Document Embeddings (File-indexed)**: Generated from the **LLM-generated summary** (to capture synthesis) or the aggregated OCR text (if summary is pending). Used for broad topic-level retrieval.
- `last_processed_hash`: Combined hash of all pages.
- `status`: `PENDING`, `DONE`, `FAILED` (for the document-level phase).

## 4. Pipeline Logic
1.  **Diff Phase**: Parser extracts page streams. Each stream is hashed and compared to the database.
2.  **Visual Phase**: Generate PNGs for new/changed pages. Assemble full PDF using cached PNGs for unchanged pages.
3.  **Intelligence Phase**: 
    - Send PNG to Gemini (with retry/backoff) for OCR. 
    - **Chunk Embeddings (Page-indexed)**: Generated per-page from raw OCR text. Ideal for "finding the needle in the haystack."
4.  **Document Phase**: 
    - Once all pages reach `DONE`, aggregate text to generate a **Whole File Summary**.
    - **Document Embeddings (File-indexed)**: Generated from the **LLM-generated summary**. This ensures the embedding captures the high-level intent and synthesis rather than just a bag of words.

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
    - Returns the structured overview (Topics, Action Items, Actions).
- **Processing Status**: `GET /api/knowledge/status/{file_id}`
    - Provides a granular view of processing progress per page.

## 6. Cleanup
- On file deletion, `NoteDeletedEvent` triggers a purge of:
    - Blob storage artifacts (PNG/PDF).
    - Database entries (OCR text, status).
    - **Vectors**: Stored as per-user `(id, vector)` pairs in the database or sidecar files. Given the small scale (1-2 users), search is performed via **exhaustive in-memory vector comparison** (e.g., NumPy cosine similarity) to avoid heavy external dependencies.

## 7. Ongoing Research
1.  **Stable Page Hashing**: Determining the most reliable way to calculate the hash of a page's stroke data from the `.note` parser.
2.  **Summary Specification**: Revisit the specific schema and implementation for the hierarchical summary after the initial design has been fleshed out.
