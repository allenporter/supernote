# Supernote Private Cloud Implementation Plan

## Phase 1: Skeleton & Tracing (Current)
- [x] Scaffold `aiohttp` server structure (`app.py`, `config.py`).
- [x] Implement request tracing middleware to `server_trace.log`.
- [x] Add `serve` CLI command.
- [x] Create basic connectivity tests.
- [x] Document setup instructions.

## Phase 2: Authentication & Session
- [x] Analyze `server_trace.log` from a real device connection.
- [x] Implement `POST /api/file/query/server` (Server Info/Check).
- [x] Implement `POST /api/terminal/equipment/unlink` (Unlink Device).
- [x] Implement `POST /api/official/user/check/exists/server` (User Exists Check).
- [x] Implement `POST /api/user/query/token` (Initial Token Check).
- [x] Implement `POST /api/official/user/query/random/code` (Challenge).
- [x] Implement `POST /api/official/user/account/login/equipment` (Device Login).
- [x] Implement `POST /api/terminal/user/bindEquipment` (Bind Device).
- [x] Implement `POST /api/user/query` (User Info).
- [x] Implement `POST /api/official/user/account/login/new` (Login).
    - [x] Handle password hashing verification.
    - [x] Issue JWT tokens.
- [x] Implement `GET /api/csrf` (if required).

## Phase 3: File Synchronization
- [x] Implement `POST /api/file/2/files/synchronous/start` (Start Sync).
- [x] Implement `POST /api/file/2/files/synchronous/end` (End Sync).
- [x] Implement `POST /api/file/2/files/list_folder` (List Folders).
- [x] Implement `POST /api/file/2/users/get_space_usage` (Capacity Check).
- [x] Implement `POST /api/file/3/files/query/by/path_v3` (File Exists Check).
- [x] Implement `POST /api/file/3/files/upload/apply` (Upload Request).
- [x] Implement `PUT /api/file/upload/data/{filename}` (File Data Upload).
- [x] Implement `POST /api/file/2/files/upload/finish` (Upload Confirmation).
- [x] Implement File Download endpoints.
    - [x] `POST /api/file/3/files/download_v3` (Get Download URL).
    - [x] `GET /api/file/download/data/{filename}` (Serve File).
- [x] Implement Directory Management (Create/Delete folders).

## Phase 4: Persistence & Storage (Completed)
- [x] Create `storage/` directory structure.
- [x] Implement `handle_upload_data` to save to `storage/temp/`.
- [x] Implement `handle_upload_finish` to move from `temp` to `storage/`.
- [x] Implement `handle_list_folder` to list actual files via Virtual File System (VFS).
- [x] Implement `handle_query_by_path` to check file existence.
- [x] Add test isolation for storage.

## Phase 5: AI & Intelligence (Completed)
- [x] Implement `GeminiService` for LLM interaction.
- [x] Implement `ProcessorService` background worker.
- [x] Implement `GeminiOcrModule` for handwriting transcription.
- [x] Implement `GeminiEmbeddingModule` for semantic indexing.
- [x] Implement `SummaryModule` for AI-generated highlights.
- [x] Implement `SearchService` for semantic search.

## Phase 6: Refactoring & Architecture (Completed)
- [x] **Data Models (Type Safety)**:
    - [x] Create `supernote/server/models/` package using `mashumaro.DataClassJSONMixin`.
    - [x] Define Request/Response dataclasses mirroring the Java DTOs/VOs (e.g., `ListFolderRequest`, `FileUploadApplyResponse`).
    - [x] Replace ad-hoc dictionary responses in `app.py` with typed objects.
- [x] **Service Layer (Business Logic)**:
    - [x] Create `supernote/server/services/` package.
    - [x] Implement `UserService`: Handle authentication, device binding, user profiles.
    - [x] Implement `FileService`: Handle file system operations, metadata management.
    - [x] Implement `BlobStorage`: Abstract disk I/O (Local CAS).
- [x] **Route Separation**:
    - [x] Split `app.py` into route modules (e.g., `admin.py`, `auth.py`, `file_device.py`, `file_web.py`, `summary.py`).
    - [x] Use `aiohttp.web.RouteTableDef` to organize routes.

## Caveats & Technical Debt (Prioritized)

### 1. Authentication & Security (**Completed**)
- [x] User authentication implemented with config-based user storage.
- [x] Random code generation and validation implemented.
- [x] JWT tokens properly signed and verified with HS256.
- [x] Token expiration implemented (configurable, default 24 hours).

### 2. File Upload Handling (**Completed**)
- [x] Robust multipart parsing and chunked upload support.

### 3. Hash Verification (**Completed**)
- [x] File upload finish verifies MD5 hash against stored blob.

### 4. Directory Traversal & Path Safety (**Completed**)
- [x] Strict path validation in VFS and FileService.

### 5. Device & Equipment Binding (**Completed**)
- [x] Persistent device binding and validation in DB.

---

## Major Features Implemented

1. **Folder and File Management**
    - Full CRUD for folders and files: create, delete, move, copy, rename, and list.
    - Recycle Bin (Soft Delete) support via Web API.

2. **User Accounts**
    - Dynamic user registration (first user = admin).
    - Password hashing and JWT-based authentication.
    - Admin CLI for user management.

3. **AI Intelligence**
    - Page-level OCR and Content Indexing.
    - Semantic Search across all notebooks.
    - Automated AI Summarization and Highlight generation.

4. **MCP Support**
    - Integration with AI agents via Model Context Protocol.

---

## Technical Omissions & Next Steps

- **Quota Enforcement:**
    - Basic usage reporting exists, but hard enforcement is missing.
- **Temp Cleanup:**
    - Stale chunks in `storage/temp` need a TTL cleanup task.
- **Core Logic Separation:**
    - Better decoupling of `aiohttp` from services for embedding in other projects (e.g., Home Assistant).
- Some errors are only logged, not returned to the client. API responses may not match official Supernote Cloud.
    - **Action:** Audit endpoints for error handling and response codes, align with official API.

### 8. Scalability & Concurrency (**Low-Medium**)
- No locking or concurrency control for uploads.
    - **Action:** Add file locks or atomic operations for concurrent uploads.

### 9. Logging & Monitoring (**Low**)
- Logging is basic; no structured logs or monitoring hooks.
    - **Action:** Add structured logging, request IDs, error monitoring.

---


## Major Features to Implement (User Priorities)

The following features are explicitly prioritized for this server:

1. **Folder and File Management**
    - Full CRUD for folders and files: create, delete, move, copy, rename, and list.
    - Directory management endpoints (create/delete folders, etc.).

2. **User Accounts (Static Config)**
    - Real user authentication and login, but user accounts can be static/config-based (not dynamic registration).
    - Proper password hashing and JWT-based authentication.

3. **Schedule and Tasks (Calendar)**
    - Full support for schedule/task APIs (create, update, delete, list tasks and groups).
    - Use the `ical` package as a backend for calendar/task storage and sync.

4. **Security Improvements**
    - Implement robust authentication, password hashing, and JWT validation.
    - Add replay/resubmit protection and improve error handling.

5. **Sync/Server Change APIs**
    - Implement endpoints for device sync and server change tracking (details TBD).

6. **(Optional) PDF/PNG Conversion**
    - Some note-to-PDF/PNG conversion logic may be implemented for export, but not as a core sync API.

---

The following features exist in the official Supernote Cloud but are **not implemented** or are **intentionally omitted** in this server:

- **Summaries/Annotations:**
    - All endpoints and logic for summary/annotation CRUD, tags, groups, and summary file upload/download are omitted.
- **PDF/PNG Conversion:**
    - Endpoints for note-to-PDF/PNG and PDF-with-mark conversion are not implemented as server APIs. (Some conversion logic may exist for export, but not as a sync API.)
- **Sharing:**
    - File sharing endpoints and logic are not implemented.
- **File Search:**
    - No endpoints for searching files by label/content.
- **Cloud/OSS/S3 Integration:**
    - No endpoints for S3/OSS integration, upload/download URLs, or cloud storage.
- **Quota/Capacity Management:**
    - Advanced quota management is not implemented; only basic usage reporting is present.
- **Feedback/Bug Reporting:**
    - No endpoints for user feedback, bug reports, or support.
- **Recycle Bin/File History:**
    - No endpoints for file recovery, recycle bin, or file versioning/history.
- **Advanced User Profile Management:**
    - No endpoints for updating user info, avatar, etc. User accounts are static/config-based, not dynamic.
- **Other Utilities:**
    - Any endpoints not explicitly listed in the plan above are not implemented.

---

## Phase 7: Advanced Features (Next)
- [ ] Database integration (SQLite/PostgreSQL) for user/file metadata.
- [ ] Docker containerization.
- [ ] SSL/TLS support (via reverse proxy instructions).

## Phase 8: Modularity & Integration (Home Assistant)
- [ ] Refactor to separate business logic from `aiohttp` handlers.
    - Goal: Allow the core logic to be used in other contexts (e.g., Home Assistant custom component).
    - Structure: `supernote.server.core` (logic) vs `supernote.server.http` (web).
- [ ] Ensure `create_app` accepts configuration objects rather than relying solely on global/env vars.
- [ ] Verify the server can be mounted as a sub-app or library.
