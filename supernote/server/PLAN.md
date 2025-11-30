# Supernote Private Cloud Implementation Plan

## Phase 1: Skeleton & Tracing (Current)
- [x] Scaffold `aiohttp` server structure (`app.py`, `config.py`).
- [x] Implement request tracing middleware to `server_trace.log`.
- [x] Add `serve` CLI command.
- [x] Create basic connectivity tests.
- [x] Document setup instructions.

## Phase 2: Authentication & Session
- [ ] Analyze `server_trace.log` from a real device connection.
- [x] Implement `POST /api/file/query/server` (Server Info/Check).
- [x] Implement `POST /api/terminal/equipment/unlink` (Unlink Device).
- [ ] Implement `POST /api/official/user/check/exists/server` (User Exists Check).
- [ ] Implement `POST /api/user/query/token` (Initial Token Check).
- [ ] Implement `POST /api/official/user/query/random/code` (Challenge).
- [x] Implement `POST /api/official/user/account/login/equipment` (Device Login).
- [x] Implement `POST /api/terminal/user/bindEquipment` (Bind Device).
- [ ] Implement `POST /api/official/user/account/login/new` (Login).
    - [ ] Handle password hashing verification.
    - [ ] Issue JWT tokens.
- [ ] Implement `GET /api/csrf` (if required).
    - [ ] Handle password hashing verification.
    - [ ] Issue JWT tokens.
- [ ] Implement `POST /api/user/query` (User Info).

## Phase 3: File Synchronization
- [ ] Implement `POST /api/file/list/query` (List Files).
- [ ] Implement File Upload/Download endpoints.
    - [ ] `POST /api/file/upload/request` (or similar).
    - [ ] `GET /api/file/download/request`.
- [ ] Implement Directory Management (Create/Delete folders).

## Phase 4: Advanced Features
- [ ] Database integration (SQLite/PostgreSQL) for user/file metadata.
- [ ] Docker containerization.
- [ ] SSL/TLS support (via reverse proxy instructions).

## Phase 5: Modularity & Integration (Home Assistant)
- [ ] Refactor to separate business logic from `aiohttp` handlers.
    - Goal: Allow the core logic to be used in other contexts (e.g., Home Assistant custom component).
    - Structure: `supernote.server.core` (logic) vs `supernote.server.http` (web).
- [ ] Ensure `create_app` accepts configuration objects rather than relying solely on global/env vars.
- [ ] Verify the server can be mounted as a sub-app or library.
