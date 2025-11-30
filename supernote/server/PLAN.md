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

## Phase 4: Persistence & Storage
- [ ] **File Storage**:
    - [ ] Create `storage/` directory in workspace.
    - [ ] Update `handle_upload_data` to save received bytes to `storage/{filename}`.
    - [ ] Update `handle_upload_finish` to verify file on disk.
- [ ] **Dynamic Metadata**:
    - [ ] Update `handle_list_folder` to scan `storage/` and return actual file entries.
    - [ ] Update `handle_query_by_path` to check `storage/` for file existence.
    - [ ] Update `handle_capacity_query` to calculate actual disk usage of `storage/`.

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

## Phase 6: Refactoring & Cleanup
- [ ] **Separation of Concerns**:
    - [ ] Create `supernote/server/logic.py` (or `service.py`) for business logic.
    - [ ] Move VO/DTO construction out of `app.py`.
    - [ ] Keep `app.py` as a thin HTTP routing layer.
- [ ] **Configuration**:
    - [ ] Make storage path configurable via `config.py`.
- [ ] **Testing**:
    - [ ] Add tests for file persistence and retrieval.

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
