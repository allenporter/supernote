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
    - [ ] Handle password hashing verification.
    - [ ] Issue JWT tokens.
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
- [ ] Implement Directory Management (Create/Delete folders).

## Phase 4: Persistence & Storage (Completed)
- [x] Create `storage/` directory structure.
- [x] Implement `handle_upload_data` to save to `storage/temp/`.
- [x] Implement `handle_upload_finish` to move from `temp` to `storage/`.
- [x] Implement `handle_list_folder` to list actual files.
- [x] Implement `handle_query_by_path` to check file existence.
- [x] Add test isolation for storage.

## Phase 5: Downloads (Completed)
- [x] Implement `handle_download_apply` (POST /api/file/3/files/download_v3).
- [x] Implement `handle_download_data` (GET /api/file/download/data).
- [x] Update `handle_list_folder` to use relative path as ID.
- [x] Add test for download flow.

## Phase 6: Refactoring & Architecture (Completed)
- [x] **Data Models (Type Safety)**:
    - [x] Create `supernote/server/models/` package using `mashumaro.DataClassJSONMixin`.
    - [x] Define Request/Response dataclasses mirroring the Java DTOs/VOs (e.g., `ListFolderRequest`, `FileUploadApplyResponse`).
    - [x] Replace ad-hoc dictionary responses in `app.py` with typed objects.
- [x] **Service Layer (Business Logic)**:
    - [x] Create `supernote/server/services/` package.
    - [x] Implement `UserService`: Handle authentication, device binding, user profiles.
    - [x] Implement `FileService`: Handle file system operations, metadata management.
    - [x] Implement `StorageService`: Abstract disk I/O (e.g., `save_file`, `list_dir`, `get_file_stream`).
- [x] **Route Separation**:
    - [x] Split `app.py` into route modules (e.g., `supernote/server/routes/auth.py`, `supernote/server/routes/file.py`).
    - [x] Use `aiohttp.web.RouteTableDef` to organize routes.
- [x] **Configuration & Dependency Injection**:
    - [x] Refactor `create_app` to accept a `Config` object.
    - [x] Inject services into route handlers (avoid global state).

## Caveats & Technical Debt (Prioritized)

### 1. Authentication & Security (**Completed**)
- [x] User authentication implemented with config-based user storage.
- [x] Random code generation and validation implemented.
- [x] JWT tokens properly signed and verified with HS256.
- [x] Token expiration implemented (configurable, default 24 hours).
    - **Status:** Production-ready authentication system.

### 2. Hardcoded Values & Placeholders (**Completed**)
- [x] All hardcoded equipment_no values replaced with request data.
- [x] User names derived from actual user accounts.
    - **Status:** All critical hardcoded values removed.

### 3. File Upload Handling (**Medium-High**)
- `trace_middleware` may consume the request body, which could break multipart parsing.
    - **Action:** Refactor middleware and upload handler for robust compatibility and error handling.

### 4. Hash Verification (**Medium**)
- File upload finish only logs a warning on hash mismatch, does not return error to client.
    - **Action:** Return error on hash mismatch, consider supporting stronger hashes.

### 5. Directory Traversal & Path Safety (**Medium**)
- Path safety checks exist but need more tests and stricter validation.
    - **Action:** Add tests, consider stricter path validation.

### 6. Device & Equipment Binding (**Medium**)
- Device binding/unlinking is stubbed, not persisted or validated.
    - **Action:** Implement persistent device binding and validation.

### 7. Error Handling & API Consistency (**Medium**)
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
