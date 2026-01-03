# Project Roadmap

This document outlines the current status, active initiatives, and future plans for the Supernote Private Cloud project. It consolidates remaining items from the original implementation plan (`supernote/server/PLAN.md`), architectural goals, and known technical debt.

## Active Initiatives

These are high-priority tasks currently in progress or recently identified as critical.

- **Data Integrity & Robustness**
  - [x] **Multi-User Clobber Detection**: Verify handling of identical content uploads by multiple users and safe deletion logic.
  - [x] **Orphaned Metadata Detection**: Implement `IntegrityService` checks for files pointing to non-existent parent directories.
  - [ ] **Capacity Checks**: Implement actual storage quota checks (currently TODO in `vfs.py`).

- **Protocol & API Compatibility**
  - [x] **OSS Endpoint Refactor**: Support `POST` requests for uploads and implicit chunk merging to match device behavior.
  - [x] **URL Signing**: Finalize transparent signature extraction and ensure fragment rejection.

- **Storage & Infrastructure**
  - [ ] **Finalize StorageService Removal**: Complete the refactoring to remove legacy `StorageService` dependencies from tests and core logic (Use `BlobStorage`/`VFS` directly).
  - [ ] Verify dangling references that create files/directores in the tests
  - [ ] Hard per-user isolation. Let's have a hard storage separating user data to avoid any any potential inter-mingling. this requires userid based enforcement in the blob store layer, or making a separate blob store instance at runtime for each user.
  - [ ] **Temp File Cleanup**: Implement TTL-based background cleanup for stale files in `storage/temp` (abandoned uploads/chunks).

## Usability
- [ ] We should have a point of view on how boostrapping the server works
- [ ] Command line utilities for the client library:
   - [ ] we shoudl be able to navigate the filesystem with the CLI
   - [ ] we should be able to upload files with the CLI
   - [ ] we should be able to download files with the CLI
   - [ ] we should be able to delete files with the CLI
   - [ ] we should be able to list files with the CLI
   - [ ] we should be able to copy files with the CLI
   - [ ] we should be able to move files with the CLI
   - [ ] we should be able to create directories with the CLI
   - [ ] we should be able to delete directories with the CLI
   - [ ] we should be able to list directories with the CLI


### Phase 7: Advanced Features
- [x] **Database Integration**: Migrate from in-memory/file-based metadata to SQLite or PostgreSQL for better scalability and query capability.
- [x] **Dockerization**: Create `Dockerfile` and `docker-compose.yml` for easy deployment.
- [ ] **SSL/TLS Support**: Document or implement reverse proxy setup (Nginx/Traefik) for secure connections.

### Phase 8: Modularity & Integration
- [ ] **Core Logic Separation**: Decouple business logic from `aiohttp` handlers to verify the server can be mounted as a sub-app or library (e.g., for Home Assistant integration).
  - *Goal*: `supernote.server.core` vs `supernote.server.http`.
- [ ] **Configuration Injection**: Ensure `create_app` fully accepts config objects, minimizing global state reliance.

### Misc
- [ ] Works with the UI. We have not tested this again the supernote web ui container.
- [ ] boostrap instructions: how do you securely get the server running, and issuing commands? e.g. enable registration, disable regstiration, what? what is the standard appraoch in the open source community for doing something like this on self hosted services. we're starting a docker container (e.g. may run on kubernetes) so cant just rely on special permissions?
- [ ] Debugability beyond logging. do we want to add a debug mode that allows us to get more information about the server's state? e.g. metrics, profiling, etc. capturing metrics and exported to prometheus
- [ ] more file recovery tooling

## Backlog & Technical Debt

### Testing
- [ ] **Test Coverage**:
  - Test upload flow with various chunk sizes (`tests/server/test_connectivity.py`).
  - Fix invalid path_display assertions in tests.
  - Add download content helper function to client library for easier testing.
- [ ] **Fix Mypy Errors**: Resolve type errors in `pyproject.toml` ignore list.

### Refactoring
- [ ] **OSS/VFS Cleanup**:
  - Determine API semantics for `soft_delete` (recursive? soft vs hard?).
  - Handle recursive copy logic in `vfs.py`.
  - Check for name collisions during directory moves/creates.
- [ ] **Auth & Routes**:
  - Implement return values and sensitive query logging in `auth.py`.
  - Standardize error responses in `file.py` to use `create_error_response`.
- [ ] **Code Cleanup**:
  - Remove dead code and unused imports in `CoordinationService`.
  - Standardize time functions (`now_ms`).

### Feature Enhancements
- [ ] **Notebook Support**:
  - Support non-X series devices in `manipulator.py`.
  - Use constants for layer counts in `parser.py`.
- [ ] **Schedule**:
  - Handle cascade delete of tasks in `schedule.py`.

## Documentation
- [ ] **Update Contributor Docs**: Ensure `CONTRIBUTING.md` reflects the latest testing and architectural standards.
