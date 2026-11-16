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

### Timestamp Precision
All `Time` fields (`creationTime`, `lastModifiedTime`, `createTime`, `updateTime`) follow the standard Supernote convention of using **Unix timestamps in milliseconds**.

### Sync Integrity Checks (`query/summary/hash`)
The `query/summary/hash` endpoint provides lightweight integrity information (`SummaryInfoItem`) rather than full summary content.
*   **Purpose**: This endpoint is designed for synchronization checks. A client can call this lightweight endpoint to see if the server has a different MD5 hash than the device, avoiding the need to download the full content unless a change is detected. It's essentially a "Sync Manifest" endpoint that allows for efficient differential updates.
