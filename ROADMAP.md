# Project Roadmap

This document outlines the path to making Supernote Private Cloud a reliable "daily driver." Priorities are shifted to focus on **Operational Readiness** (can I run it safely?) and **Data Safety** (will I lose my notes?) before adding new features.

## Phase 1: Operational Readiness ("Daily Driver")
*Goal: Securely deploy the server for personal daily use.*

- [x] **Bootstrap & Deployment Guide**:
    - Document standard secure setup (Docker/Kubernetes).
    - Define how to handle registration/secrets securely in a self-hosted context.
- [x] **SSL/TLS Support**:
    - Document reverse proxy setup (Nginx/Traefik) for secure HTTPS connections (essential for real device usage).
- [x] **Web UI Compatibility**:
    - Verify server works against the official Supernote Web UI container (ultimate compatibility check).
- [x] **Dockerization**:
    - (Done) Basic Dockerfile exists. Verified with the bootstrap guide.
- [x] **Security & Identity**:
    - [x] Security review for all the auth and user flows.
    - [x] Understand reset password semantics and how it works securely.
    - [x] Abuse protection (e.g. tracking error counts, rate limiting).
- [x] **Documentation**:
    - [x] Refresh stale README.md and update examples.

## Phase 2: Safety & Integrity ("Trustworthy Storage")
*Goal: Ensure data is never lost, corrupted, or leaked.*

- [x] **Hard Per-User Isolation**:
    - Enforce strict storage separation per user to prevent cross-contamination.
- [ ] **Temp File Cleanup (TTL)**:
    - Implement background task to clean up stale uploads/chunks in `storage/temp`.
- [ ] **Capacity & Quota Enforcement**:
    - Implement actual storage quota checks based on user limits.
    - Implement proper quota allocation values and understand `AllocationVO`.
- [x] **Finalize Legacy Cleanup**:
    - Remove all dependencies on legacy `StorageService`.
    - Audit use of `file_server`, `inner name`, and `bucket` fields for consistency.
- [x] **Data Integrity & Typing**:
    - [x] Email address canonicalization for unique identity.
    - [x] Typed "password" object (MD5 vs raw strings).
    - [x] Typed "hash" objects (MD5, SHA256) for integrity checks.
- [x] **Sync Safety**:
    - Review use of "syn" field to prevent data loss during synchronization.
- [x] **Recycle Bin Support**:
    - Implement soft-delete and recovery via Web API.

## Phase 3: Usability & Tooling
*Goal: Improve the experience of managing and debugging the server.*

- [x] **CLI Improvements**:
    - Expand CLI to support filesystem operations (upload, download, list, move, delete) via `supernote cloud`.
- [x] **Observability**:
    - Add trace logging to inspect server state.
- [x] **Architecture & Client Refactoring**:
    - [x] Reconcile Client libraries (reconcile `Supernote` with specific APIs).
    - [x] File vs Device APIs: Organize routes and models by API type; bridge gaps.

## Phase 4: Intelligence & AI
*Goal: Unlock the value of your notes with OCR and AI.*

- [x] **OCR Pipeline**:
    - [x] Implement background processing to extract text from `.note` files.
- [x] **Full-Text Search**:
    - [x] Index OCR'd text to allow searching note contents (not just filenames).
- [x] **AI Summarization**:
    - [x] Generate summaries of notes or daily roll-ups using LLMs (Gemini).

## Phase 5: Advanced Features & Compatibility
*Goal: Feature parity and wider device support.*

- [x] **Schedule/Calendar**:
    - [x] Handle cascade delete of tasks.
- [x] **MCP Integration**:
    - [x] Expose Supernote data via Model Context Protocol.
- [ ] **Core Logic Separation**:
    - Decouple `aiohttp` handlers to allow embedding in Home Assistant.


### Testing & Quality
- [x] **Test Coverage**:
    - Upload flow with various chunk sizes.
    - Fix invalid assertions (path_display).
    - Expand general coverage (currently 300+ tests).
- [ ] **Static Analysis**:
    - Fix Mypy errors for `supernote/notebook/` and `supernote/cli/`.
- [x] **Error Handling**:
    - Define `ErrorCode` as an enum and use the `error_code` field uniformly.
    - Improve handling of specific backend errors (e.g., SQLAlchemy) to avoid leaking details.
- [x] **Test Structure Refactor**:
    - Reorganize tests to match module structure.

### Refactoring
- [ ] **VFS Semantics**:
    - Clarify generic `soft_delete` and recursive copy logic.
- [ ] **Code Cleanup**:
    - Remove dead code in `CoordinationService`.
- [ ] **Multi-host Client Authentication**:
    - Update `FileCacheAuth` and `Client` to support multiple hosts simultaneously.
