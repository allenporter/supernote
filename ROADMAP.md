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

### Testing & Quality
- [ ] **Test Coverage**:
    - Upload flow with various chunk sizes.
    - Fix invalid assertions (path_display).
- [ ] **Static Analysis**:
    - Fix Mypy errors.

### Refactoring
- [ ] **VFS Semantics**:
    - Clarify generic `soft_delete` and recursive copy logic.
- [ ] **Code Cleanup**:
    - Remove dead code in `CoordinationService`.
