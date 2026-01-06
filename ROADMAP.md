# Project Roadmap

This document outlines the path to making Supernote Private Cloud a reliable "daily driver." Priorities are shifted to focus on **Operational Readiness** (can I run it safely?) and **Data Safety** (will I lose my notes?) before adding new features.

## Phase 1: Operational Readiness ("Daily Driver")
*Goal: Securely deploy the server for personal daily use.*

- [x] **Bootstrap & Deployment Guide**:
    - Document standard secure setup (Docker/Kubernetes).
    - Define how to handle registration/secrets securely in a self-hosted context.
- [ ] **SSL/TLS Support**:
    - Document reverse proxy setup (Nginx/Traefik) for secure HTTPS connections (essential for real device usage).
- [x] **Web UI Compatibility**:
    - Verify server works against the official Supernote Web UI container (ultimate compatibility check).
- [x] **Dockerization**:
    - (Done) Basic Dockerfile exists. Needs verifying with the bootstrap guide.
- [ ] **Security & Identity**:
    - [ ] Security review for all the auth and user flows.
    - [ ] Understand reset password semantics and how it works securely.
    - [ ] Abuse protection (e.g. tracking error counts, rate limiting).
- [ ] **Documentation**:
    - [ ] Refresh stale README.md and update examples.

## Phase 2: Safety & Integrity ("Trustworthy Storage")
*Goal: Ensure data is never lost, corrupted, or leaked.*

- [ ] **Hard Per-User Isolation**:
    - Enforce strict storage separation per user to prevent cross-contamination.
- [ ] **Temp File Cleanup (TTL)**:
    - Implement background task to clean up stale uploads/chunks in `storage/temp`.
- [ ] **Capacity & Quota Enforcement**:
    - Implement actual storage quota checks based on user limits.
    - Implement proper quota allocation values and understand `AllocationVO`.
- [ ] **Finalize Legacy Cleanup**:
    - Remove all dependencies on legacy `StorageService`.
    - Audit use of `file_server`, `inner name`, and `bucket` fields for consistency.
- [ ] **Data Integrity & Typing**:
    - [ ] Email address canonicalization for unique identity.
    - [ ] Typed "password" object (MD5 vs raw strings).
    - [ ] Typed "hash" objects (MD5, SHA256) for integrity checks.
- [ ] **Sync Safety**:
    - Review use of "syn" field to prevent data loss during synchronization.

## Phase 3: Usability & Tooling
*Goal: Improve the experience of managing and debugging the server.*

- [ ] **CLI Improvements**:
    - Expand CLI to support filesystem operations (upload, download, list, move, delete).
- [ ] **Observability**:
    - Add metrics (Prometheus) or debug endpoints to inspect server state.
- [ ] **Architecture & Client Refactoring**:
    - [ ] Reconcile Client libraries (reconcile `SupernoteClient` with specific APIs).
    - [ ] File vs Device APIs: Organize routes and models by API type; bridge gaps.

## Phase 4: Intelligence & AI
*Goal: Unlock the value of your notes with OCR and AI.*

- [ ] **OCR Pipeline**:
    - Implement background processing to extract text from `.note` files.
- [ ] **Full-Text Search**:
    - Index OCR'd text to allow searching note contents (not just filenames).
- [ ] **AI Summarization**:
    - Generate summaries of notes or daily roll-ups using LLMs.

## Phase 5: Advanced Features & Compatibility
*Goal: Feature parity and wider device support.*

- [ ] **Schedule/Calendar**:
    - Handle cascade delete of tasks.
- [ ] **Core Logic Separation**:
    - Decouple `aiohttp` handlers to allow embedding in Home Assistant.


### Testing & Quality
- [ ] **Test Coverage**:
    - Upload flow with various chunk sizes.
    - Fix invalid assertions (path_display).
    - Expand general coverage (currently unprioritized).
- [ ] **Static Analysis**:
    - Fix Mypy errors.
- [ ] **Error Handling**:
    - Define `ErrorCode` as an enum and use the `error_code` field uniformly.
    - Improve handling of specific backend errors (e.g., SQLAlchemy) to avoid leaking details.
- [ ] **Test Structure Refactor**:
    - Reorganize tests to match module structure (`test_` prefix in the same directory).
    - Move API tests into the `routes` subdirectory.

### Refactoring
- [ ] **VFS Semantics**:
    - Clarify generic `soft_delete` and recursive copy logic.
- [ ] **Code Cleanup**:
    - Remove dead code in `CoordinationService`.
- [ ] **Multi-host Client Authentication**:
    - Update `FileCacheAuth` and `Client` to support multiple hosts simultaneously.
