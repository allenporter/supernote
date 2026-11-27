# Summary API Overview

This document provides a high-level overview of the Summary ecosystem in the Supernote cloud, designed to help developers implement features like OCR-generated summaries.

## Core Concepts

The system revolves around three main entities: **Summaries**, **Summary Groups**, and **Summary Tags**.

### Summaries (`SummaryDO`)
A "Summary" represents an individual **Digest** entry in the Supernote Partner App and tablet Digest UI—such as a PDF/EPUB highlight excerpt or a server-generated AI notebook synthesis.

*   **Conceptual Role**: Holds a single Digest card (quote, excerpt, or AI synthesis) plus optional text/handwriting annotations.
*   **Key Fields**:
    *   `uniqueIdentifier`: **32-character lowercase hex identifier** (or client UUID) used for device/Partner App Digest synchronization.
    *   `content`: Primary text content (excerpt or Markdown synthesis).
    *   `sourcePath`: VFS-relative path to the source file without a leading slash (e.g., `Note/Meeting.note` or `Document/Archive/Paper.pdf`).
    *   `isSummaryGroup`: Set to `"N"` for Digest items.
    *   `parentUniqueIdentifier`: Points to the `uniqueIdentifier` of the Digest's **Category** (`SummaryGroup`). Empty (`""`) or `None` appears under **Uncategorized** in the Partner App.

### Summary Groups (`SummaryDO` with `isSummaryGroup='Y'`)
A "Summary Group" maps directly to a **Category** in the Supernote Partner App and tablet Digest filter bar (*All*, *Uncategorized*, and custom categories).

*   **Conceptual Role**: Top-level Digest Category. Because each `SummaryDO` has a single `parentUniqueIdentifier`, a Digest entry belongs to at most one Category.
*   **Key Fields**:
    *   `uniqueIdentifier`: 32-character lowercase hex identifier for the category.
    *   `isSummaryGroup`: Set to `"Y"`.
    *   `name`: Category display name (for example, `"AI Summaries"` for server-generated notebook syntheses).

### Summary Tags (`SummaryTagDO`)
Legacy/auxiliary tag endpoints (`/api/file/*/summary/tag`) defined in the cloud API schema.

*   **Usage Note**: The Supernote Partner App and Digest 2.0 UI organize digests by **Categories** (`SummaryGroup` via `parentUniqueIdentifier`) and **Sources** (`sourcePath`), leaving `SummaryTagDO` and `SummaryDO.tags` unused (`null`).

---

## Interoperability Workflow (Custom Digest / AI Synthesis)

If you are building an integration that publishes Digest cards (such as AI syntheses or reading excerpts) for Supernote files:

### Identify the Source File & Path
Use the VFS-relative path without a leading slash (e.g., `Note/Daily.note` or `Document/Archive/Paper.pdf`) for `sourcePath` so the Partner App groups items accurately under **Sources**.

### Ensure a Category (`SummaryGroup`) If Desired
If you want the Digest card filed under a named **Category** rather than **Uncategorized**:
1. Query existing categories via `POST /api/file/query/summary/group` (`QuerySummaryGroupDTO`).
2. If absent, create one via `POST /api/file/add/summary/group` (`AddSummaryGroupDTO`) using a 32-character lowercase hex `uniqueIdentifier` (for example `uuid.uuid5(...).hex`).

### Create or Update the Digest Entry
Call `POST /api/file/add/summary` (`AddSummaryDTO`) or `PUT /api/file/update/summary` (`UpdateSummaryDTO`):
*   `uniqueIdentifier`: Deterministic 32-character lowercase hex identifier (or client UUID).
*   `parentUniqueIdentifier`: The target Category's `uniqueIdentifier` (or `""` / omitted for **Uncategorized**).
*   `content`: Markdown synthesis or excerpt text.
*   `sourcePath`: VFS-relative path (e.g., `Note/Daily.note`).

## Data Model Reference

### SummaryItem Field Guide

| Field | Type | Description |
| :--- | :--- | :--- |
| `uniqueIdentifier` | `string` | 32-character lowercase hex identifier (or client UUID) used for Digest sync. |
| `parentUniqueIdentifier` | `string` | Links a Digest item to a **Category** (`SummaryGroup`); `""` or `null` renders under **Uncategorized**. |
| `isSummaryGroup` | `string` | `"Y"` if this item is a Category (`SummaryGroup`), `"N"` for leaf Digest cards. |
| `content` | `string` | Excerpt text or Markdown synthesis. |
| `sourcePath` | `string` | VFS-relative path without leading `/` (e.g., `Note/Daily.note`, `Document/Book.pdf`). |
| `tags` | `string` | Legacy comma-separated tag names (unused by Partner App Digest 2.0). |
| `creationTime` | `int64` | Unix timestamp in **milliseconds**. |
| `metadata` | `string` | JSON-encoded string (e.g., `segments` on AI summaries, or `document_location_data` / `author` on device PDF digests). |

---

## Technical Implementation Nuances

### Category Assignment & Preservation
Each `SummaryDO` links to at most one `SummaryGroup` (`Category`) via `parentUniqueIdentifier`. Server-generated notebook syntheses default to a per-user `"AI Summaries"` category on initial creation, and leave `parentUniqueIdentifier` unchanged on subsequent updates so manual Partner App category moves stick permanently.

### Handwriting Metadata
The fields `handwriteInnerName` and `handwriteMD5` refer to binary stroke data stored in the Object Storage (OSS).
*   `handwriteInnerName`: The unique key in OSS where the handwriting file is located.
*   `handwriteMD5`: Used to verify the integrity of the downloaded stroke data.

### Text vs. Handwritten Digests & Source References
A Digest card can contain plain text, handwritten ink, or both:
*   **Text Digests** store their excerpt or synthesis in `content` (and an optional typed note in `commentStr`), with no binary attachment.
*   **Handwritten Digests** attach a standalone `.mark` stroke file (`handwriteInnerName` + `handwriteMD5`) holding the stylus comment written inside the Digest app. Although it uses the same binary stroke format as Supernote notebooks, it is a self-contained annotation canvas for that Digest card—not a document-level `.pdf.mark` margin-annotation sidecar overlaid on top of a PDF.
*   **Optional source links**: `fileId` and `sourcePath` are nullable, loose references with no foreign-key cascade. Highlights taken from a PDF/EPUB or server-generated AI notebook summaries populate them so clients can group cards under **Sources**, while standalone Digests created directly in the Digest app (and Category groups) leave them unset. Moving or deleting a source PDF or notebook does not delete its Digests or their `.mark` blobs.

### Handwriting Blob & Render Cache Lifecycle
Handwritten Digests store two separate artifacts with different durability rules:
1.  **Upload (`USER_DATA_BUCKET`)**: The client requests a signed upload URL via `POST /api/file/upload/apply/summary`, uploads the raw `.mark` file to `USER_DATA_BUCKET`, and records `handwriteInnerName` and `handwriteMD5` on `SummaryDO` via `add/summary` or `update/summary`.
2.  **On-demand rendering (`CACHE_BUCKET`)**: Calling `POST /api/extended/file/summary/to/pdf` or `/to/png` renders the `.mark` file into `CACHE_BUCKET` under `conversions/{user_id}/summary_{summary_id}/handwrite_{handwrite_md5}.pdf` (or `_page_{n}.png`) and returns signed `/api/oss/summary/*` download URLs.
3.  **Update**: Editing only text fields keeps the cached renders intact. Replacing `handwriteInnerName` publishes `BlobCleanupEvent` so `FileService` deletes the superseded `.mark` blob once no `SummaryDO` or `UserFileDO` references it. Updating `handwriteMD5` (or clearing handwriting) emits `SummaryUpdatedEvent`, and `ConversionService` removes stale renders for that summary from `CACHE_BUCKET`.
4.  **Soft delete**: Deleting a summary (or deleting its parent Category, which cascades to all active children) marks `SummaryDO.is_deleted = True` and emits `SummaryDeletedEvent`.
    *   `CACHE_BUCKET` renders for `conversions/{user_id}/summary_{summary_id}/` are deleted immediately, because soft-deleted summaries are unreachable and re-adding the same `uniqueIdentifier` creates a new row with a new `summary_id`.
    *   The raw `.mark` blob in `USER_DATA_BUCKET` is retained for the 30-day recycle retention window (`RECYCLE_RETENTION_MS`) in case a device re-adds the same `uniqueIdentifier` referencing that blob.
5.  **Hard purge & integrity backstop**: Every 5 minutes, `SummaryService.purge_expired_summaries` hard-deletes soft-deleted rows past `RECYCLE_RETENTION_MS` and emits `BlobCleanupEvent` to reclaim their `.mark` blobs from `USER_DATA_BUCKET`. `IntegrityService` also flags any unreferenced blobs in either bucket during periodic integrity checks.

### Optional Fields & Caveats
*   **All links and annotations are optional**: A Digest card does not need a source file (`fileId`/`sourcePath`), a Category (`parentUniqueIdentifier`), a typed comment (`commentStr`), or a handwriting attachment (`handwriteInnerName`/`handwriteMD5`).
*   **No restore-in-place**: Soft-deleted summaries cannot be un-deleted under the same `id`. Calling `add/summary` with the same `uniqueIdentifier` removes the prior row and inserts a new row with a new `summary_id`.
*   **No source-file cascade**: `fileId` and `sourcePath` are informational links; renaming, moving, or deleting the referenced PDF/notebook does not update or delete the Digest or its `.mark` blob.
*   **On-demand rendering only**: Uploading a `.mark` blob does not trigger background rendering. `/api/extended/file/summary/to/pdf` and `/to/png` render lazily on first request and require both `handwriteInnerName` (present in `USER_DATA_BUCKET`) and a valid `handwriteMD5`.
*   **Asynchronous cache cleanup**: Stale `CACHE_BUCKET` renders are removed asynchronously via `LocalEventBus` subscribers. If a server restart drops an in-flight cleanup task or an active row is replaced in place via `add/summary` with a duplicate `uniqueIdentifier`, `IntegrityService` catches and repairs any remaining orphaned cache blobs.

### Rendering Handwriting (Extended)
`POST /api/file/download/summary` returns the raw `.mark` stroke file. To get the ink rendered instead, call one of the server's extended endpoints with the same `{"id": <summaryId>}` body:
*   `POST /api/extended/file/summary/to/pdf` -> `{"url": "<signed /api/oss/summary/pdf/{id} URL>"}`
*   `POST /api/extended/file/summary/to/png` -> `{"pngPageVOList": [{"pageNo": 0, "url": "<signed /api/oss/summary/png/{id}/{pageNo} URL>"}]}`

The summary must belong to the caller and have `handwriteInnerName` set, otherwise the endpoint returns `404`. Renders are cached in `CACHE_BUCKET` keyed by summary ID and `handwriteMD5`, so an edited comment re-renders and downloads never serve stale ink from a previous version. Static `sn_...` API keys are accepted, so automation clients (for example n8n) can fetch the ink without shell access. Python clients can use `SummaryClient.summary_to_pdf` / `SummaryClient.summary_to_png`.

### Timestamp Precision
All `Time` fields (`creationTime`, `lastModifiedTime`, `createTime`, `updateTime`) follow the standard Supernote convention of using **Unix timestamps in milliseconds**.

### Sync Integrity Checks (`query/summary/hash`)
The `query/summary/hash` endpoint provides lightweight integrity information (`SummaryInfoItem`) rather than full summary content.
*   **Purpose**: This endpoint is designed for synchronization checks. A client can call this lightweight endpoint to see if the server has a different MD5 hash than the device, avoiding the need to download the full content unless a change is detected. It's essentially a "Sync Manifest" endpoint that allows for efficient differential updates.
