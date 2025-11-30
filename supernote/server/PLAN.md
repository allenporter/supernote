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
- [ ] Implement File Download endpoints.
    - [ ] `POST /api/file/3/files/download_v3` (Get Download URL).
    - [ ] `GET /api/file/download/data/{filename}` (Serve File).
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

## Phase 6: Refactoring & Architecture (Next)
- [ ] Refactor `app.py` into multiple files (controllers, services).
- [ ] Introduce `mashumaro` models for request/response.
- [ ] Implement proper error handling and logging.
- [ ] Add proper locking for concurrent access.

## Phase 5: Downloads (Cloud-to-Device)
- [ ] **Download Endpoints**:
    - [ ] Implement `POST /api/file/3/files/download_v3`:
        - [ ] Validate file exists.
        - [ ] Generate download URL (e.g., `/api/file/download/data/{filename}`).
    - [ ] Implement `GET /api/file/download/data/{filename}`:
        - [ ] Serve file content from `storage/`.
- [ ] **Sync Logic**:
    - [ ] Ensure `handle_list_folder` sets `is_downloadable: true` for files.
    - [ ] Handle `content_hash` (MD5) to avoid unnecessary downloads.

## Phase 6: Refactoring & Architecture
- [ ] **Data Models (Type Safety)**:
    - [ ] Create `supernote/server/models.py` using `mashumaro.DataClassJSONMixin`.
    - [ ] Define Request/Response dataclasses mirroring the Java DTOs/VOs (e.g., `ListFolderRequest`, `FileUploadApplyResponse`).
    - [ ] Replace ad-hoc dictionary responses in `app.py` with typed objects.
- [ ] **Service Layer (Business Logic)**:
    - [ ] Create `supernote/server/services/` package.
    - [ ] Implement `UserService`: Handle authentication, device binding, user profiles.
    - [ ] Implement `FileService`: Handle file system operations, metadata management.
    - [ ] Implement `StorageService`: Abstract disk I/O (e.g., `save_file`, `list_dir`, `get_file_stream`).
- [ ] **Route Separation**:
    - [ ] Split `app.py` into route modules (e.g., `supernote/server/routes/auth.py`, `supernote/server/routes/file.py`).
    - [ ] Use `aiohttp.web.RouteTableDef` to organize routes.
- [ ] **Configuration & Dependency Injection**:
    - [ ] Refactor `create_app` to accept a `Config` object.
    - [ ] Inject services into route handlers (avoid global state).

## Phase 7: Advanced Features
- [ ] Database integration (SQLite/PostgreSQL) for user/file metadata.
- [ ] Docker containerization.
- [ ] SSL/TLS support (via reverse proxy instructions).

## Phase 5: Modularity & Integration (Home Assistant)
- [ ] Refactor to separate business logic from `aiohttp` handlers.
    - Goal: Allow the core logic to be used in other contexts (e.g., Home Assistant custom component).
    - Structure: `supernote.server.core` (logic) vs `supernote.server.http` (web).
- [ ] Ensure `create_app` accepts configuration objects rather than relying solely on global/env vars.
- [ ] Verify the server can be mounted as a sub-app or library.
