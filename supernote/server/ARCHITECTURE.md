# Open Private Cloud Server Architecture & Wire Protocol

This document describes the architecture of the **Open Private Cloud for Supernote** Python server (`supernote.server`) and the Supernote Private Cloud wire protocol it implements.

## 1. Architecture Overview

Open Private Cloud is an asynchronous Python server built to run as a lightweight, self-hosted alternative using a single SQLite database and local file storage:

- **HTTP / Web Framework**: `aiohttp` (`supernote/server/app.py`) serving device sync endpoints, Web UI routes, signed object storage endpoints, and the static Vue 3 Web UI (`supernote/server/static/`).
- **Database**: SQLAlchemy 2.0 (async) with `aiosqlite` and Alembic migrations (`supernote/alembic/`) backed by a single SQLite file.
- **Coordination & Session State**: `CoordinationService` (`SqliteCoordinationService`, backed by `KeyValueDO`) manages login challenges, stateful JWT sessions, sync session locks, and single-use URL signing nonces.
- **Virtual Filesystem & Storage**: `VirtualFileSystem` and `FileService` track the logical folder tree in `UserFileDO` (`f_user_file`) and soft-deleted items in `RecycleFileDO` (`f_recycle_file`), while `LocalBlobStorage` stores binary file content on disk by bucket (`supernote-user-data`, `supernote-cache`).
- **Authentication**: Challenge-response login issuing `HS256` JWTs (`x-access-token` header) backed by session state in `CoordinationService`.
- **Notebook Rendering & Processing**: `ConversionService` and `ProcessorService` use the local `supernote.notebook` library to render `.note` files to PNG/PDF on demand, and optionally run OCR, summarization, and vector embeddings.
- **Real-Time Messaging**: `SocketIOServerManager` (`supernote/server/socket.py`, powered by `python-socketio` with Engine.IO v3 compatibility middleware) subscribes to `LocalEventBus` and pushes sync notifications to connected Supernote devices.

---

## 2. Authentication Protocol

The authentication flow uses a challenge-response mechanism involving a short-lived random challenge code and timestamp to prevent replay attacks.

### 2.1. Get Random Code (Challenge)

**Endpoint**: `POST /api/official/user/query/random/code`

**Request (`RandomCodeDTO`)**:
```json
{
  "account": "user@example.com",
  "countryCode": "+1"
}
```

**Response (`RandomCodeVO`)**:
```json
{
  "success": true,
  "randomCode": "12345678",
  "timestamp": "1678888888000"
}
```

`UserService` stores the challenge in `CoordinationService` under `challenge:{account}:{timestamp}` with a 5-minute TTL.

### 2.2. Login

**Endpoint**: `POST /api/official/user/account/login/new` (or `POST /api/official/user/account/login/equipment` for device logins)

**Request (`LoginDTO`)**:
```json
{
  "account": "user@example.com",
  "password": "SHA256_HASH_OF_PASSWORD",
  "timestamp": "1678888888000",
  "equipmentNo": "SN100B...",
  "equipment": 3,
  "loginMethod": "2"
}
```

`equipment` indicates the client type (`1`: Web, `2`: App, `3`: Terminal/Device, `4`: Platform).

**Password Hashing Logic**:
1. **MD5 Hash**: `md5_pass = MD5(plain_text_password)` (stored on `UserDO.password_md5`).
2. **Salted SHA256 Hash**: `client_hash = SHA256(md5_pass + randomCode)`.
3. On verification, the server consumes (`pop_value`) the challenge from `CoordinationService` and compares `SHA256(user.password_md5 + random_code)` using constant-time `hmac.compare_digest`.

**Response (`LoginVO`)**:
```json
{
  "success": true,
  "token": "eyJ0eXAiOiJKV1Qi...",
  "counts": "0",
  "isBind": "Y",
  "isBindEquipment": "Y",
  "userName": "user@example.com",
  "soldOutCount": 0
}
```

### 2.3. Token Usage & Revocation

- **Header**: `x-access-token: <token>` (also accepted via cookie or query parameter where applicable, e.g., `.ics` feeds).
- **Signing Key**: Configured via `SUPERNOTE_JWT_SECRET` / `auth.secret_key`, or auto-generated as a random 256-bit secret and persisted in `CoordinationService` (`system:jwt_secret_key`).
- **Session Validation**: Every authenticated request verifies both the JWT signature/expiration and active session state in `CoordinationService`, allowing individual device unlinks, password resets, or global key rotation to revoke tokens immediately.

---

## 3. File Synchronization Protocol

Device synchronization runs inside a locked session lifecycle (`Start -> List / Upload / Download / Delete -> End`).

### 3.1. Start Sync Session

**Endpoint**: `POST /api/file/2/files/synchronous/start`

**Request (`SynchronousStartLocalDTO`)**:
```json
{
  "equipmentNo": "SN100B..."
}
```

**Behavior**: Checks `CoordinationService` (`sync:lock:{user_id}`, 300 s TTL) to ensure no other device is concurrently syncing the same account. If another device holds the lock, the server returns HTTP `409` with error code `E0078`. Also returns `synType` indicating whether initial sync has already completed (`sync:initialized:{user_id}`).

### 3.2. List Files

**Endpoint**: `POST /api/file/3/files/list_folder_v3` (and `POST /api/file/2/files/list_folder` by path)

**Request (`ListFolderLocalDTO`)**:
```json
{
  "id": 0,
  "recursive": true,
  "equipmentNo": "SN100B..."
}
```

**Response (`ListFolderLocalVO`)**:
```json
{
  "success": true,
  "equipmentNo": "SN100B...",
  "entries": [
    {
      "id": "1001",
      "name": "MyNote.note",
      "tag": "file",
      "size": 1024,
      "content_hash": "MD5_HASH",
      "path_display": "/MyNote.note",
      "parent_path": "/",
      "is_downloadable": true,
      "lastUpdateTime": 1678888888000
    }
  ]
}
```

Synchronization is **state-based**: the client fetches server entries and compares MD5 hashes (`content_hash`) and paths against local state to decide uploads, downloads, or deletions (`POST /api/file/3/files/delete_folder_v3`).

### 3.3. Upload File

Uploads use a three-step flow: **Apply** (request signed upload URLs) -> **Transfer** -> **Finish** (verify MD5 and commit VFS metadata).

**Step A: Apply (`POST /api/file/3/files/upload/apply`)**

Request (`FileUploadApplyLocalDTO`):
```json
{
  "path": "/Note/MyNote.note",
  "fileName": "MyNote.note",
  "size": "1024",
  "equipmentNo": "SN100B..."
}
```

Response (`FileUploadApplyLocalVO`): returns `innerName` plus signed `fullUploadUrl` (`/api/oss/upload?path=...&signature=...`) and `partUploadUrl` (`/api/oss/upload/part?path=...&signature=...`) for chunked uploads.

**Step B: Transfer (`POST /api/oss/upload` or `POST|PUT /api/oss/upload/part`)**

The client uploads multipart file bytes (`file` field) to the signed URL. For chunked uploads, parts are written under chunk keys and merged into the target blob in `USER_DATA_BUCKET` once the final part arrives (`partNumber == totalChunks`).

**Step C: Finish (`POST /api/file/2/files/upload/finish`)**

Request (`FileUploadFinishLocalDTO`):
```json
{
  "path": "/Note/MyNote.note",
  "fileName": "MyNote.note",
  "innerName": "...",
  "content_hash": "MD5_HASH_OF_FILE",
  "equipmentNo": "SN100B..."
}
```

`FileService.finish_upload` validates the stored blob's MD5 against `content_hash`, creates or updates the `UserFileDO` row in SQLite, updates `CapacityDO`, and emits a VFS event onto `LocalEventBus`.

### 3.4. Download File

1. **Apply (`POST /api/file/3/files/download_v3`)**: Looks up the `UserFileDO` entry by `id`, verifies ownership, and returns `FileDownloadLocalVO` containing a signed `url` (`/api/oss/download?path={id}&signature=...`).
2. **Transfer (`GET /api/oss/download`)**: Verifies the URL signature via `UrlSigner` and streams bytes (with HTTP `Range` support) from `LocalBlobStorage`.

### 3.5. End Sync Session

**Endpoint**: `POST /api/file/2/files/synchronous/end`

**Request (`SynchronousEndLocalDTO`)**:
```json
{
  "equipmentNo": "SN100B...",
  "flag": "Y"
}
```

Releases `sync:lock:{user_id}` if held by `equipmentNo`. When `flag != "N"`, marks `sync:initialized:{user_id}`, runs opportunistic expired recycle-bin pruning, and publishes `SyncCompletedEvent` onto `LocalEventBus`.

---

## 4. Signed Object Storage URLs (`/api/oss/`)

`UrlSigner` (`supernote/server/utils/url_signer.py`) secures `/api/oss/*` upload and download URLs without requiring `x-access-token` headers on direct blob transfers:

- **Mechanism**: Appends a `signature` query parameter containing an `HS256` JWT signed with the server secret key.
- **Signed Claims**: Embeds the target `path`, `user` email, expiration (`exp`, default 15 minutes), and a unique `nonce` (`jti`).
- **Single-Use vs. Reusable Tokens**: Upload URLs enforce single-use nonce consumption in `CoordinationService` (or consume on the final chunk for multipart uploads), while download URLs allow range requests within the expiry window (`single_use=False`).

---

## 5. Persistence & Real-Time Events

### 5.1. Virtual Filesystem & Storage (`UserFileDO` & `LocalBlobStorage`)

- **Metadata Tree (`UserFileDO` in `f_user_file`)**: Stores logical files and folders (`directory_id = 0` for root, `is_folder = "Y" | "N"`, `is_active = "Y" | "N"`, `md5`, `size`, and `storage_key`).
- **Recycle Bin (`RecycleFileDO` in `f_recycle_file`)**: Tracks soft-deleted items with deletion timestamps so web deletions can be restored or pruned.
- **Disk Layout**: `LocalBlobStorage` persists raw file payloads in flat bucket directories keyed by `storage_key` (`innerName`), avoiding filesystem path-escaping issues and duplicate metadata directories.

### 5.2. Notebook Conversion & Background Processing

- **On-Demand Export (`ConversionService`)**: `POST /api/file/note/to/pdf` and `POST /api/file/note/to/png` load the `.note` blob from `USER_DATA_BUCKET`, render pages locally in-process using `supernote.notebook` (`PdfConverter` / `ImageConverter`), and cache outputs in `CACHE_BUCKET`.
- **Background Worker (`ProcessorService`)**: Watches `LocalEventBus` for file uploads and updates, executing page hashing, PNG preview rasterization, and optional OCR, summarization, and embedding pipelines (`supernote/server/services/processor_modules/`).

### 5.3. Socket.IO Notifications

`SocketIOServerManager` (`supernote/server/socket.py`) accepts device connections at `/socket.io/` (authenticating `token`, `type`, `random`, and HMAC-SHA256 `sign` via `supernote/server/socket_auth.py`). When `LocalEventBus` receives `VfsItem*`, `SyncCompletedEvent`, `ScheduleUpdatedEvent`, or `Summary*` events, the server pushes `ServerMessage` (`FILE-SYN`), `to-do` (`TASK-SYN`), or `digest` (`DIGEST-SYN`) hints so paired devices trigger background sync. For full event schemas, see [api-spec/socket-io.md](../../api-spec/socket-io.md).
