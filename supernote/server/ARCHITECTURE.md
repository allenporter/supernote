# Supernote Server Architecture & Protocol Guide

This document provides a comprehensive guide to the Supernote server architecture and protocol. It is intended to assist in re-implementing the server or creating compatible clients.

## 1. Architecture Overview

The Supernote server is a **Spring Boot** application using **MyBatis** for data access and **Redis** for caching and session management.

-   **Framework**: Spring Boot
-   **Database**: MySQL (inferred from Mapper usage)
-   **Cache**: Redis (used for tokens, locks, and temporary codes)
-   **Storage**: Local file system (NAS mode) or S3-compatible storage (Cloud mode). The analyzed code focuses on the "Local/NAS" mode (`F_FileLocalController`).
-   **Authentication**: JWT (JSON Web Tokens) with HMAC256.

## 2. Authentication Protocol

The authentication flow uses a challenge-response mechanism involving a random code and timestamp to prevent replay attacks.

### 2.1. Get Random Code (Challenge)
**Endpoint**: `POST /api/official/user/query/random/code`

**Request (`RandomCodeDTO`)**:
```json
{
  "account": "user@example.com",
  "countryCode": "+1" // Optional if email
}
```

**Response (`RandomCodeVO`)**:
```json
{
  "randomCode": "12345678",
  "timestamp": 1678888888000
}
```

### 2.2. Login
**Endpoint**: `POST /api/official/user/account/login/new` (or `/api/official/user/account/login/equipment` for devices)

**Request (`LoginDTO`)**:
```json
{
  "account": "user@example.com",
  "password": "SHA256_HASH_OF_PASSWORD",
  "timestamp": 1678888888000, // From Step 2.1
  "equipmentNo": "SN100B...", // Required for equipment login
  "equipment": 3, // 1: Web, 2: App, 3: Terminal (Device), 4: User Platform
  "loginMethod": "2" // 1: Phone, 2: Email, 3: WeChat
}
```

**Password Hashing Logic**:
1.  **MD5 Hash**: `md5_pass = MD5(plain_text_password)`
2.  **SHA256 Hash**: `final_pass = SHA256(md5_pass + randomCode)`
    *   *Note*: If the server stores plain text passwords (unlikely), step 1 might be skipped. However, legacy code suggests MD5 is the base storage format.

**Response (`LoginVO`)**:
```json
{
  "token": "eyJ0eXAiOiJKV1Qi...",
  "userId": 12345,
  ...
}
```

### 2.3. Token Usage
-   **Header**: `x-access-token: <token>`
-   **Secret**: The JWT signature secret is a long hardcoded string in `JwtTokenUserUtil`.
    -   Legacy/Fallback Secret: `<REDACTED_SECRET>` (See `SENSITIVE.md`)

## 3. File Synchronization Protocol

The file synchronization process involves a session lifecycle (Start -> List/Upload/Download -> End).

### 3.1. Start Sync Session
**Endpoint**: `POST /api/file/2/files/synchronous/start`

**Request**:
```json
{
  "equipmentNo": "SN100B..."
}
```
**Logic**: Checks Redis lock to ensure no other device is syncing the same account.

### 3.2. List Files
**Endpoint**: `POST /api/file/3/files/list_folder_v3`

**Request**:
```json
{
  "id": 0, // 0 for root directory
  "recursive": true,
  "equipmentNo": "SN100B..."
}
```

**Response**:
```json
{
  "entries": [
    {
      "id": "1001",
      "name": "MyNote.note",
      "tag": "file", // "file" or "folder"
      "size": 1024,
      "content_hash": "MD5_HASH",
      "path_display": "/MyNote.note",
      "lastUpdateTime": 1678888888000
    },
    ...
  ]
}
```

**Sync Logic**:
The synchronization appears to be **state-based**. The client lists the server's file state (MD5 hashes) and compares it with the local state.
-   **Upload**: If local file is new or has different MD5 -> Upload.
-   **Download**: If server file is new or has different MD5 -> Download.
-   **Delete**: If file is missing on one side (and marked for deletion) -> Delete (handled by `delete_folder_v3`).

### 3.3. Upload File
Uploads are a two-step process: Apply (Get URL) -> Upload -> Finish (Confirm).

**Step A: Apply**
**Endpoint**: `POST /api/file/3/files/upload/apply`

**Request**:
```json
{
  "path": "/Folder/Note.note",
  "fileName": "Note.note",
  "size": "1024",
  "equipmentNo": "SN100B..."
}
```

**Response**:
```json
{
  "fullUploadUrl": "http://server/api/oss/upload?signature=...&path=...",
  "authorization": "...", // Signature
  "timestamp": "...",
  "nonce": "..."
}
```

**Step B: Transfer**
Upload the file content to `fullUploadUrl` using `POST` (multipart/form-data).

**Step C: Finish**
**Endpoint**: `POST /api/file/2/files/upload/finish`

**Request**:
```json
{
  "path": "/Folder/Note.note",
  "fileName": "Note.note",
  "size": "1024",
  "content_hash": "MD5_HASH_OF_FILE",
  "equipmentNo": "SN100B..."
}
```

### 3.4. Download File
**Endpoint**: `POST /api/file/3/files/download_v3`

**Request**:
```json
{
  "id": 1001,
  "equipmentNo": "SN100B..."
}
```

**Response**:
```json
{
  "url": "http://server/api/oss/download?path=...&signature=..."
}
```

### 3.5. End Sync Session
**Endpoint**: `POST /api/file/2/files/synchronous/end`

**Request**:
```json
{
  "equipmentNo": "SN100B..."
}
```

## 4. Internal Security & Signing

### 4.1. OSS/Local File Signing
The `O_OssLocalController` uses a signature to secure direct file access.

-   **Secret Key**: `<REDACTED_SECRET>` (See `SENSITIVE.md` for local dev, generate a new one for your server)
-   **Path Encryption**: Base64 (URL Safe, No Padding) of the UTF-8 path.
-   **Signature Algorithm**: `HMAC-SHA256` (Hex encoded).

**Upload Signature**:
`SHA256Hex(encryptedPath + timestamp + nonce + fileSize + secretKey)`

**Download Signature**:
`SHA256Hex(encryptedPath + timestamp + nonce + secretKey)`

## 5. Data Models

### 5.1. UserFileDO (Database)
Represents a file or folder.
-   `id`: Long (Primary Key)
-   `userId`: Long
-   `directoryId`: Long (Parent Folder ID, 0 for root)
-   `fileName`: String
-   `isFolder`: "Y" or "N"
-   `md5`: String (File content hash)
-   `size`: Long
-   `createTime`: Date
-   `updateTime`: Date

### 5.2. FileActionDO
Tracks changes for synchronization logic.
-   `action`: "A" (Add), "D" (Delete), "U" (Update), "M" (Move/Rename)
-   `fileId`: Long
-   `md5`: String

## 6. Re-implementation Plan

To re-implement this server:

1.  **Database Schema**: Recreate tables for `user_file`, `file_action`, `user`, `user_equipment`.
2.  **Auth Service**: Implement the Challenge-Response login and JWT issuance.
3.  **File Service**:
    -   Implement `list_folder` (recursive query).
    -   Implement `upload/apply` (generate signed URLs).
    -   Implement `upload/finish` (update DB, handle versioning).
    -   Implement `download` (generate signed URLs).
4.  **Storage Service**: Implement the `/api/oss/` endpoints to handle actual file I/O and validate signatures.

## 7. Deep Dive: File Synchronization & Architecture

This section provides a detailed breakdown of the file synchronization logic, data structures, and corner cases to consider during re-implementation.

### 7.1. Core Data Structures

#### 7.1.1. UserFileDO (The "Truth")
The `UserFileDO` table represents the current state of the file system.
-   **`directoryId`**: Implements a hierarchical structure. `0` is the root.
-   **`innerName`**: The actual filename on the disk/storage (likely a UUID or hash to prevent collisions), while `fileName` is the display name.
-   **`md5`**: Critical for sync. The client compares this hash to determine if a file has changed.
-   **`isFolder`**: "Y" or "N". Folders are virtual; they exist as rows in this table but don't necessarily have a physical file on disk (size 0).

#### 7.1.2. FileActionDO (The "Journal")
The `FileActionDO` table acts as an event log or journal of changes. This is likely used to help clients catch up on changes they missed, or for the "History" feature.
-   **`action`**:
    -   `A`: Add (Create/Upload)
    -   `D`: Delete
    -   `U`: Update (Content change)
    -   `M`: Move/Rename
    -   `R`: Rename (specifically for files?)
    -   `DM`: Delete Move (part of a move operation?)
    -   `DR`: Delete Rename
-   **`path` / `newPath`**: Stores the full path context for the action.

### 7.2. Synchronization Logic Details

#### 7.2.1. Listing Files (`listFolder` / `listFolderV2`)
-   **Recursive vs. Flat**: The API supports both. `recursive=true` fetches the entire tree.
-   **Path Handling**: The server calculates `path_display` dynamically by traversing the `directoryId` hierarchy or using cached path logic.
-   **Comparison**: The client sends a request, gets the list of `EntriesVO`, and performs a local diff:
    -   **Server has, Client missing**: Download.
    -   **Client has, Server missing**: Upload (if new) or Delete locally (if server deleted it - *Note: This requires checking the Action log or assuming the server is the source of truth*).
    -   **MD5 Mismatch**: Conflict! The server logic seems to favor "Last Write Wins" or "Server Wins" in simple cases, but the existence of `FileActionDO` suggests more complex conflict resolution might be possible.

#### 7.2.2. Upload Flow (`uploadApply` -> `uploadFinish`)
1.  **Apply**:
    -   Client sends metadata (path, size, name).
    -   Server generates a **Signed URL** (`O_OssLocalController`).
    -   **Corner Case**: If a file with the same name exists, the server might return an error or handle it in the `finish` step.
2.  **Transfer**:
    -   Client uploads binary data to the signed URL.
    -   The file is stored temporarily or directly in the target path (depending on implementation).
3.  **Finish**:
    -   Client confirms upload with the final MD5.
    -   **Critical Logic**:
        -   If the file exists (`querybyNameAndDirectoryId` returns result):
            -   Update `md5`, `size`, `innerName`.
            -   Log `U` (Update) action.
        -   If the file is new:
            -   Insert new `UserFileDO`.
            -   Log `A` (Add) action.
    -   **Socket Notification**: The server sends a Socket.IO message (`finishFolderMessage`) to notify other connected devices of the change.

#### 7.2.3. Deletion (`deleteFolder`)
-   **Soft vs. Hard Delete**:
    -   The code moves the file to a "Recycle Bin" (implied by `RecycleFileDO` and `RecycleFileMapper` usage in other parts, though `deleteFolder` in `FileLocalServiceImpl` seems to perform a hard delete from `UserFileDO` and insert into `FileActionDO` with action `D`).
    -   **Corner Case**: Deleting a folder must recursively delete all children (`deleteUnder`). The `FileLocalServiceImpl` handles this by finding all children and deleting them.

### 7.3. Corner Cases & "Gotchas"

1.  **Path Separators**: The code explicitly handles `/` stripping (`path.substring(1)`). Ensure your implementation is consistent with leading slashes.
2.  **Concurrency**:
    -   **Redis Locks**: The server uses `cloudLockedSeconds` (Redis key `lock_cloud_userId`) to prevent simultaneous syncs from the same user on different devices.
    -   **Race Conditions**: If two devices upload the same file name simultaneously, the "Finish" step might race. The database transaction in `uploadFinish` should handle this, but "Last Write Wins" is the likely outcome.
3.  **Special Characters**: The `FileUtil` or `LocalFileUtil` likely has logic to sanitize filenames. The `innerName` concept (storing files by UUID/Hash on disk) avoids filesystem issues with special characters.
4.  **Large Files**: The `upload/part` endpoint in `O_OssLocalController` suggests support for **Chunked Uploads**. If you implement the client, you should support chunking for reliability.
5.  **Empty Folders**: Since folders are virtual rows in the DB, ensure `createFolder` correctly inserts a row with `isFolder="Y"` and `size=0`.

### 7.4. Re-implementation Checklist

-   [ ] **Database**: `user_file` table with `directory_id` adjacency list pattern.
-   [ ] **Storage**: Store files on disk using a content-addressable scheme (e.g., `storage/MD5_HASH`) or UUIDs (`innerName`) to avoid duplicates and filename issues.
-   [ ] **Locking**: Implement the Redis-based locking mechanism to prevent sync corruption.
-   [ ] **Socket.IO**: (Optional but recommended) Implement the notification events so clients update in real-time.

## 8. File Conversion Architecture

The server delegates file conversion tasks (Note -> PDF, Note -> PNG) to an external service referred to as **QTServer**.

### 8.1. Protocol
-   **Transport**: Raw TCP Socket.
-   **Address**: Configurable via `ip` and `port` (likely internal network).
-   **Message Format**:
    -   **Header**: 8-byte ASCII string representing the length of the JSON payload (zero-padded).
    -   **Body**: JSON payload.
    -   *Example*: `00000123{"busCode":"T01",...}`

### 8.2. Operations

#### 8.2.1. Note to PDF (`T01`)
-   **BusCode**: `T01`
-   **Input**: `TransferDTO`
    -   `downloadUrl`: URL where QTServer can download the source `.note` file.
    -   `postAuthorization`: Signature for uploading the result.
    -   `url`: Upload destination URL.
-   **Output**: `TransferVO` (Status/Result).

#### 8.2.2. Note to PNG (`T02`)
-   **BusCode**: `T02`
-   **Input**: `TransferPngDTO`
    -   `downloadUrl`: Source file URL.
    -   `transferUrlDTOList`: List of upload URLs for each page image.
-   **Output**: `TransferVO`.

#### 8.2.3. Get Page Count (`T03`)
-   **BusCode**: `T03`
-   **Input**: `TransferNotePageDTO`
    -   `downloadUrl`: Source file URL.
-   **Output**: `TransferPageVO` (Contains page count/metadata).

### 8.3. Implementation Note
Since the conversion logic is proprietary (likely involving the Ratta Supernote rendering engine), a re-implementation of the server would need to:
1.  **the `.note` format** already described in `supernote-lite` python library.
2.  **Implement a local renderer** (using the python library) to replace the external QTServer calls.
3.  **Mock the QTServer protocol** OR rewrite the `FileLocalServiceImpl` to call the python library directly instead of opening a TCP socket.
