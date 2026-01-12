# Summary API Overview

This document provides a high-level overview of the Summary ecosystem in the Supernote cloud, designed to help developers implement features like OCR-generated summaries.

## Core Concepts

The system revolves around three main entities: **Summaries**, **Summary Groups**, and **Summary Tags**.

### 1. Summaries (`SummaryDO`)
A "Summary" is a generic container for derived content associated with a user's file (e.g., a handwritten note).

*   **Conceptual Role**: It holds the "result" of an operation on a file. This could be OCR text, a digest, or user notes.
*   **Key Fields**:
    *   `uniqueIdentifier`: **Client-Provided UUID**. This is the primary key used to link the summary to the source file on the device. It must be unique.
    *   `content`: The actual text content (e.g., OCR result).
    *   `sourcePath`: path to the original file (e.g., `/Note/Meeting.note`).
    *   `isSummaryGroup`: Set to `"N"` for standard summaries.
    *   `parentUniqueIdentifier`: If the summary belongs to a group (folder), this points to the group's UUID.

### 2. Summary Groups (`SummaryDO` with `isSummaryGroup='Y'`)
A "Summary Group" is simply a folder or container for other summaries.

*   **Conceptual Role**: Acts as a directory to organize summaries.
*   **Key Fields**:
    *   `uniqueIdentifier`: The group's own UUID.
    *   `isSummaryGroup`: Set to `"Y"`.
    *   `name`: The display name of the group.

### 3. Summary Tags (`SummaryTagDO`)
Tags are labels that can be created and managed separately to categorize content.

*   **Conceptual Role**: A pool of available tags (e.g., "Work", "Urgent", "Ideas").
*   **Usage**: While `SummaryTagDO` manages the *existence* of tags, the `SummaryDO` object itself has a `tags` string field where you likely store a comma-separated list of tag names or IDs to associate them with a specific summary.

---

## Interoperability Workflow (e.g., Gemini OCR)

If you are building an external tool (like a Gemini OCR bot) to generate summaries for Supernote files, follow this workflow:

### Step 1: Identify the Source File
You need the **UUID** that the device/client uses to refer to the file.
*   *Note*: This is NOT the cloud database ID (`fileId`). It is the consistent ID used by the client validation logic.
*   **Action**: Ensure your client tracks this UUID.

### Step 2: Generate Content
Run your OCR or processing logic on the file to generate the text string.

### Step 3: Create the Summary
Call the `POST /api/file/add/summary` endpoint (represented by `AddSummaryDTO`).
*   **Payload Construction**:
    *   `uniqueIdentifier`: Provide the file's UUID (or a new UUID if this is a standalone summary).
    *   `content`: Your Gemini OCR text.
    *   `sourcePath`: The file path (for reference).
    *   `md5Hash`: (Optional) Hash of the content for integrity.
    *   `isSummaryGroup`: `"N"`

### Step 4: Organization (Optional)
*   **Grouping**: If you want this summary inside a specific folder, create a group first (via `add/summary/group`), get its UUID, and pass that as `parentUniqueIdentifier` when creating the summary.
*   **Tagging**: If you want to tag it, passed a string to the `tags` field.

## Data Model Reference

### SummaryItem Field Guide

| Field | Type | Description |
| :--- | :--- | :--- |
| `uniqueIdentifier` | `string` | **Crucial**: The primary key for device-to-cloud mapping. Should match the source `fileId` UUID on the Supernote device. |
| `parentUniqueIdentifier` | `string` | Links a summary to a Summary Group (Folder). |
| `isSummaryGroup` | `string` | `"Y"` if this item is a container, `"N"` for content items. |
| `content` | `string` | Typically stores OCR-derived text or user-provided summary markdown. |
| `tags` | `string` | Comma-separated list of tag names. Loose association with `SummaryTagDO`. |
| `creationTime` | `int64` | Unix timestamp in **milliseconds**. |
| `metadata` | `string` | JSON-encoded string for extensible plugin/system data. |

---

## Technical Implementation Nuances

### 1. UUID Mapping (`uniqueIdentifier`)
The `uniqueIdentifier` is used by the Supernote device to locate summaries associated with its local files. When generating a summary for a specific note, this field must perfectly match the UUID the device uses to identify that note. If they mismatch, the summary won't "attach" to the file in the device UI.

### 2. Loose Tagging
The system uses "loose association" for tags:
*   `SummaryTagDO` entries define the *existence* of a tag (name/UI color).
*   `SummaryDO` items store tag names as a static string in the `tags` field.
*   **Implication**: Renaming a tag in `SummaryTagDO` does not automatically update the `tags` string in related summaries. The client must handle these cascading updates if strict consistency is desired.

### 3. Handwriting Metadata
The fields `handwriteInnerName` and `handwriteMD5` refer to binary stroke data stored in the Object Storage (OSS).
*   `handwriteInnerName`: The unique key in OSS where the handwriting file is located.
*   `handwriteMD5`: Used to verify the integrity of the downloaded stroke data.

### 4. Timestamp Precision
All `Time` fields (`creationTime`, `lastModifiedTime`, `createTime`, `updateTime`) follow the standard Supernote convention of using **Unix timestamps in milliseconds**.

### 5. Sync Integrity Checks (`query/summary/hash`)
The `query/summary/hash` endpoint provides lightweight integrity information (`SummaryInfoItem`) rather than full summary content.
*   **Purpose**: This endpoint is designed for synchronization checks. A client can call this lightweight endpoint to see if the server has a different MD5 hash than the device, avoiding the need to download the full content unless a change is detected. It's essentially a "Sync Manifest" endpoint that allows for efficient differential updates.
