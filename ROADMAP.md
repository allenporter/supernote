# Project Roadmap

This document outlines the path to making Supernote Private Cloud a reliable "daily driver." Priorities are shifted to focus on **Operational Readiness** (can I run it safely?) and **Data Safety** (will I lose my notes?) before adding new features.

## Phase 1: Operational Readiness ("Daily Driver")
*Goal: Securely deploy the server for personal daily use.*

- [ ] **Bootstrap & Deployment Guide**:
    - Document standard secure setup (Docker/Kubernetes).
    - define how to handle registration/secrets securely in a self-hosted context.
- [ ] **SSL/TLS Support**:
    - Document reverse proxy setup (Nginx/Traefik) for secure HTTPS connections (essential for real device usage).
- [ ] **Web UI Compatibility**:
    - Verify server works against the official Supernote Web UI container (ultimate compatibility check).
- [x] **Dockerization**:
    - (Done) Basic Dockerfile exists. Needs verifying with the bootstrap guide.

## Phase 2: Safety & Integrity ("Trustworthy Storage")
*Goal: Ensure data is never lost, corrupted, or leaked.*

- [ ] **Hard Per-User Isolation**:
    - Enforce strict storage separation (e.g., separate blob store instances or root paths) per user to prevent cross-contamination.
- [ ] **Temp File Cleanup (TTL)**:
    - Implement background task to clean up stale uploads/chunks in `storage/temp`.
- [ ] **Capacity & Quota Enforcement**:
    - Implement actual storage quota checks based on user limits.
- [ ] **Finalize Legacy Cleanup**:
    - Remove all dependencies on legacy `StorageService` to simplify the architecture.
    - Verify no "dangling references" in tests create unexpected files.

## Phase 3: Usability & Tooling
*Goal: Improve the experience of managing and debugging the server.*

- [ ] **CLI Improvements**:
    - Expand CLI to support filesystem operations (upload, download, list, move, delete) for easier management without the Web UI.
- [ ] **Observability**:
    - Add metrics (Prometheus) or debug endpoints to inspect server state beyond simple logs.

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

## Backlog & Technical Debt

### Uncategorized

These features have not ben categorized or prioritized yet in the roadmap.

- [ ] The readme is getting stale and out of date
   - [ ] Examples may no longer be accurate
- [ ] Separate Client libraries: We originally started off with SupernoteClient then added separate file, schedule, etc APIs. We should reconcile this (e.g. remove supernote client) and use the more specific ones
    - [ ] The SupernoteClient.from_credentials helper is nice, maybe we want though to wrap that for Login Client to return a simple object that we can persist with the filecache etc. We have server url, etc as well.
- [ ] File vs Device APIs. We should (1) organize apis by device vs web APIs in the data model, (2) organize implementation the server by routes (3) decide current gaps and what to do about them. (e.g. do we want to reorganize the client library base don device vs web)
- [ ] Abuse protection (e.g. tracking error counts, showing captchas, etc)
- [ ] Determine if we need any email address canonicalization for user entry vs unique email address in the database
- [ ] Security review for all the auth and user flows.
- [ ] Understand reset password semantics and how it works securely, what is the end to end flow etc
- [ ] Make a typed "password" object that we can use for all password related operations (e.g. validated that its in M55 format to not get confused with raw strings)
- [ ] Make a typed "hash" object for other types of content hashes (e.g. md5, sha256, etc) stored in the database for integrity checks
- [ ] Audit use of the "file_server" field in the database and ensure it is used consistently
- [ ] Audit use of the "inner name" and "bucket" fields for storage systems.
- [ ] Implement proper quota allocation value.
- [ ] Understand AllocationVO implementation details and tag.


### Testing & Quality
- [ ] **Test Coverage**:
    - Upload flow with various chunk sizes.
    - Fix invalid assertions (path_display).
- [ ] **Static Analysis**:
    - Fix Mypy errors.
- [ ] **Error Handling**:
    - Implement proper error handling for all HTTP responses.
    - We have error codes in supernote.models.base that should be defined as an enum.
    - We have a "error_code" field that we are not currently using, and error messages are not used uniformly.
    - Specific backend errors need to be handled better/uniformly. Sqlalchemy errors are raised all the way to caller/HTTP response.
- [ ] **Test Coverage**: We have not looked closely at test coverage or prioritized where to expand.


### Refactoring
- [ ] **VFS Semantics**:
    - Clarify generic `soft_delete` and recursive copy logic.
- [ ] **Code Cleanup**:
    - Remove dead code in `CoordinationService`.
- [ ] **Multi-host Client Authentication**:
    - Update `FileCacheAuth` and `Client` to support storing and retrieving credentials for multiple hosts simultaneously.
- [ ] Test structure: The current tests are not structured well. We need tests for each module, rather than arbitrary tests based on one unique case. These tests should be in the same directory as the module they test, with the same name as the module, and "test_" prefix. We should probably move the api tests in the routes subdirectory.
