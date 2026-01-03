# File Service Architecture Proposal

## Current State
Currently, `FileService` is tightly coupled to the API Layer. It directly instantiates and returns Data Transfer Objects (DTOs) and View Objects (VOs) defined in the API models (`models.file_web`, `models.file_device`, `models.file_common`).

**Issues:**
1.  **High Coupling**: Changes to the API contract (JSON structure) require changes to the Service Layer.
2.  **Protocol Mixing**: The Service Layer contains logic branches that return different types of objects (`EntriesVO` vs `UserFileVO`) depending on whether it's serving a Web or Device request, rather than just returning the data.
3.  **Testing**: Tests assert against API artifacts rather than business logic results.

## Ideal Architecture
In a clean layered architecture, the Service Layer should return **Domain Entities**.

1.  **Service Layer**: Returns internal Domain Objects (e.g., `UserFileDO`, or a rich `FileNode` dataclass). It knows *nothing* about `EntriesVO` or `UserFileVO`.
2.  **Route Layer**: Responsible for the "Last Mile" translation. It calls the Service, gets a Domain Object, and maps it to the specific VO/DTO required by that endpoint.
    *   `file_device.py`: Maps `UserFileDO` -> `EntriesVO`
    *   `file_web.py`: Maps `UserFileDO` -> `UserFileVO`

## The "Path Resolution" Challenge
The primary friction in moving to this architecture is the logic required to calculate `path_display` and `parent_path`.

Currently, `FileService` calculates these during listing/search by traversing the `VirtualFileSystem` (VFS).
*   **Device API (`EntriesVO`)** requires: `path_display` (Full path like `/Notes/Meeting.pdf`) and `parent_path`.
*   **Web API (`UserFileVO`)** does not strictly require full paths in the same way (it often works with IDs), but sometimes implicitly needs context.

**If we simply return `UserFileDO` (Database Object) from the Service:**
The Route Layer would receive a raw DO which only knows its `directory_id` (parent ID) and `file_name`. It does *not* know its full path. The Route handler would then need to query the VFS again to resolve the path, which is inefficient and leaks logic.

## Proposed Solution: Rich Domain Objects

Refactor `FileService` to return a rich intermediate object, for example `FileEnity`.

```python
@dataclass
class FileEntity:
    """Domain object representing a file in the system."""
    id: int
    parent_id: int
    name: str
    is_folder: bool
    size: int
    md5: str | None
    create_time: int
    update_time: int
    
    # Contextual fields computed by the service
    full_path: str | None = None
    parent_path: str | None = None
```

### Workflow
1.  **Service**: `list_folder(user)` -> returns `list[FileEntity]`.
    *   The Service performs the necessary heavy lifting (SQL joins or VFS recursion) to populate `full_path` efficiently.
2.  **Device Route**:
    *   Receives `FileEntity`.
    *   Maps to `EntriesVO(path_display=entity.full_path, ...)`
3.  **Web Route**:
    *   Receives `FileEntity`.
    *   Maps to `UserFileVO(file_name=entity.name, ...)`

### Benefits
*   **Decoupled**: Service doesn't care if the API adds a new field or renames `path_display` to `filePath`.
*   **Reusable**: The same `list_folder` method calls can support CLI tools, Admin interfaces, or future protocols.

## Recommendation
For the current phase of refactoring:
1.  **Acknowledge the debt**: The current implementation is functional but coupled.
2.  **Checkpoint**: Keep this proposal for the next major refactor cycle.
3.  **Next Step (Optional)**: If specific pain points arise (e.g., needing to support a CLI that prints files differently), implement `FileEntity` then.
