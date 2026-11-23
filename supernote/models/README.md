# API Data Model for Supernote Private Cloud Protocol

This module (`supernote.models`) describes the shared wire-format Data Transfer Objects (DTOs) and Value Objects (VOs) used by the **Open Private Cloud for Supernote** (`supernote.client` and `supernote.server`). These models serve as a reference for both client and server implementations looking to interoperate with the Supernote Private Cloud protocol. While this may also work with hosted public endpoints, it is intended for self-hosted servers so as not to place extra load on Ratta's servers.

Endpoints are organized by functional domain so clients and server handlers share a consistent model of the protocol.

---

## Serialization Architecture

All request DTOs and response VOs are Python `@dataclass` models backed by `mashumaro` (`DataClassJSONMixin` / `DataClassORJSONMixin` compatible):

* **CamelCase Wire Aliasing**: Python fields use `snake_case` with `field(metadata=field_options(alias="camelCase"))` and `serialize_by_alias = True` in `BaseConfig` so serialized JSON matches the exact camelCase keys expected by Supernote hardware firmware and the web UI.
* **Stringified 64-Bit Snowflake IDs**: To preserve full precision across JavaScript `JSON.parse()` clients and hardware sync payloads, 64-bit Snowflake ID fields (`file_id`, `id`, `directory_id`, etc.) use `field_options(serialize=str)` on wire serialization.
* **Unified Response Envelope (`supernote.models.base.BaseResponse`)**: All server API responses inherit from `supernote.models.base.BaseResponse`, carrying `success: bool`, `error_code: str | None` (`errorCode`), and `error_msg: str | None` (`errorMsg`), plus shared enums (`ErrorCode`, `BooleanEnum`, `ProcessingStatus`, `TaskType`).

| Submodule | Primary Scope | Key Classes |
| :--- | :--- | :--- |
| `supernote.models.base` | Base response envelope & shared enums | `BaseResponse`, `ErrorCode`, `BooleanEnum`, `ProcessingStatus`, `TaskType`, `create_error_response` |
| `supernote.models.auth` | Challenge-response, SMS, and token authentication | `RandomCodeDTO`, `RandomCodeVO`, `LoginDTO`, `LoginVO`, `SmsLoginDTO`, `QueryTokenVO` |
| `supernote.models.user` | User accounts, registration, and profile queries | `UserRegisterDTO`, `UserInfoVO`, `UserQueryByIdVO`, `UpdatePasswordDTO`, `RetrievePasswordDTO` |
| `supernote.models.file_common` | Shared file/folder entries and upload grant VOs | `EntriesVO`, `FileUploadApplyLocalVO`, `FileSortOrder`, `FileSortSequence`, `UploadType` |
| `supernote.models.file_web` | Web UI directory listing, search, and recycle bin | `FileListQueryDTO`, `FileListQueryVO`, `UserFileVO`, `RecycleFileListVO`, `FilePathQueryVO` |
| `supernote.models.file_device` | Hardware V2/V3 sync, path queries, and PNG/PDF conversion | `ListFolderV2DTO`, `ListFolderLocalVO`, `FileUploadApplyLocalDTO`, `NoteToPngVO`, `NoteToPdfVO` |
| `supernote.models.schedule` | To-Do task groups, tasks, and recurrence payloads | `ScheduleTaskGroupItem`, `ScheduleTaskInfo`, `AddScheduleTaskDTO`, `UpdateScheduleTaskListDTO` |
| `supernote.models.summary` | Handwritten/AI summaries, summary groups, and tags | `SummaryItem`, `SummaryGroupItem`, `AddSummaryDTO`, `QuerySummaryVO`, `QuerySummaryMD5HashVO` |
| `supernote.models.extended` | Self-hosted semantic search, transcripts, API keys, and AI status | `WebSearchRequestDTO`, `WebSearchResponseVO`, `WebTranscriptResponseVO`, `CreateApiKeyDTO`, `ApiKeyVO`, `WebAiStatusVO` |
| `supernote.models.webhook` | Outbound HMAC-signed webhook event payloads | `WebhookPayload`, `WebhookFileVO`, `EVENT_NOTE_SYNC_COMPLETED`, `EVENT_NOTE_PROCESSING_COMPLETED` |
| `supernote.models.socket` | Real-time Socket.IO events (`FILE-SYN`, `TASK-SYN`, `DIGEST-SYN`) | `SocketHandshakeParams`, `SocketIoClientMessage`, `SocketMessageData`, `SocketTaskMessageData` |
| `supernote.models.equipment` | Hardware device activation and binding | `ActivateEquipmentDTO`, `BindEquipmentDTO`, `UnbindEquipmentDTO`, `UserEquipmentVO` |
| `supernote.models.system` | OSS multipart chunks, queue status, and storage integrity | `FileChunkVO`, `UploadFileVO`, `QueueStatusVO`, `IntegrityReportVO`, `ReferenceSysParamDTO` |

---

## Authentication & User Management (`supernote.models.auth`, `supernote.models.user`)

See `supernote.models.auth` and `supernote.models.user` for more information on the data models related to these API endpoints.

### Login & Logout

Endpoints for user login, logout, and session token validation.

*   `POST /api/official/user/account/login/new`: Account Login (`LoginDTO` -> `LoginVO`)
*   `POST /api/official/user/account/login/equipment`: Device Token Login (`LoginDTO` -> `LoginVO`)
*   `POST /api/user/sms/login`: SMS Login (`SmsLoginDTO` -> `SmsLoginVO`)
*   `POST /api/user/logout`: Logout (`BaseResponse`)
*   `POST /api/user/query/loginRecord`: Query Login History
*   `POST /api/user/query/token`: Validate/Query Token (`QueryTokenDTO` -> `QueryTokenVO`)
*   `POST /api/official/user/query/random/code`: Get Random Code for login crypto (`RandomCodeDTO` -> `RandomCodeVO`)

### User Profile

Endpoints for reading and updating user profiles.

*   `POST /api/user/check/exists`: Check User Exists (`UserCheckDTO` -> `UserCheckVO`)
*   `POST /api/official/user/check/exists/server`: Check User Exists (Server Aware)
*   `POST /api/user/query`: Query Current User (`UserQueryVO`)
*   `POST /api/user/query/info`: Query User Info (`UserInfoVO`)
*   `POST /api/user/update`: Update User Info (`UpdateUserDTO` -> `BaseResponse`)
*   `POST /api/user/update/name`: Update Nickname
*   `POST /api/user/query/all`: Query All Users
*   `PUT /api/user/freeze`: Freeze/Unfreeze Account
*   `POST /api/user/query/one`: Query Single User
*   `GET /api/user/query/user/{userId}`: Query User by ID (`UserQueryByIdVO`)

### Registration

Endpoints for account registration and account deletion.

*   `POST /api/user/register`: User Registration (`UserRegisterDTO` -> `BaseResponse`)
*   `POST /api/user/account/clear`: Delete Account (**WARNING**: permanently deletes the user account and all cloud files, blobs, recycle bin items, summaries, schedule tasks, and active sessions)

### Password & Security

Endpoints for password recovery and updates.

*   `POST /api/official/user/retrieve/password`: Retrieve Password (`RetrievePasswordDTO` -> `BaseResponse`)
*   `PUT /api/user/password`: Change Password (`UpdatePasswordDTO` -> `BaseResponse`)

### Validation Codes

Endpoints for issuing and verifying email and captcha validation codes.

*   `POST /api/user/mail/validcode`: Send Email Validation Code
*   `POST /api/user/check/validcode`: Verify Code
*   `GET /api/base/pic/code`: Get Graphic Verification Code

### Account Settings

Endpoints for updating account settings.

*   `PUT /api/user/email`: Update Email Address (`UpdateEmailDTO` -> `BaseResponse`)

---

## File Management — Web & General (`supernote.models.file_web`, `supernote.models.file_common`)

See `supernote.models.file_web` and `supernote.models.file_common` for more information on the data models related to these API endpoints.

### Web File Operations

Endpoints for web browser and desktop file management, recycle bin recovery, and direct uploads/downloads.

*   `POST /api/file/list/query`: List Files & Folders (`FileListQueryDTO` -> `FileListQueryVO`)
*   `POST /api/file/folder/list/query`: List Folders Only (`FolderListQueryDTO` -> `FolderListQueryVO`)
*   `POST /api/file/capacity/query`: Query Storage Usage (`CapacityVO`)
*   `POST /api/file/delete`: Delete File/Folder (`FileDeleteDTO`)
*   `POST /api/file/folder/add`: Create New Folder (`FolderAddDTO`)
*   `POST /api/file/move`: Move File/Folder (`FileMoveAndCopyDTO`)
*   `POST /api/file/copy`: Copy File/Folder (`FileMoveAndCopyDTO`)
*   `POST /api/file/rename`: Rename File/Folder (`FileReNameDTO`)
*   `POST /api/file/list/search`: Search Files
*   `POST /api/file/path/query`: Get File Path Info (`FilePathQueryDTO` -> `FilePathQueryVO`)
*   **Recycle Bin:**
    *   `POST /api/file/recycle/list/query`: List Recycle Bin (`RecycleFileListDTO` -> `RecycleFileListVO`)
    *   `POST /api/file/recycle/clear`: Empty Recycle Bin
    *   `POST /api/file/recycle/delete`: Permanently Delete (`RecycleFileDTO`)
    *   `POST /api/file/recycle/revert`: Restore File (`RecycleFileDTO`)
*   **Upload/Download:**
    *   `POST /api/file/download/url`: Get Download URL (`FileDownloadDTO` -> `FileDownloadUrlVO`)
    *   `POST /api/file/upload/apply`: Request Upload (`FileUploadApplyDTO` -> `FileUploadApplyLocalVO`)
    *   `POST /api/file/upload/finish`: Complete Upload (`FileUploadFinishDTO` -> `BaseResponse`)

### Basic File Ops

Legacy endpoints for basic file and folder queries.

*   `POST /api/file/add/folder/file/deleteApi`: Add Folder/File (Desktop)
*   `POST /api/file/2/files/query/deleteApi`: Query File (Dropbox style)
*   `POST /api/file/2/files`: Query File by Path

### File Search

Endpoints for searching files by label or name.

*   `POST /api/file/label/list/search`: Search by Label/Name (`FileLabelSearchDTO` -> `FileLabelSearchVO`)

### Terminal Specific

Endpoints for device terminal file upload workflows.

*   `POST /api/file/terminal/upload/apply`: Terminal Upload Request
*   `POST /api/file/terminal/upload/finish`: Terminal Upload Complete

---

## Cloud/NAS Synchronization — Device API (`supernote.models.file_device`)

Endpoints used by physical Supernote devices during Cloud/Private Cloud synchronization. See `supernote.models.file_device` for more information on the data models related to these API endpoints.

### Sync Handshake

Endpoints for acquiring and releasing per-user synchronization session locks.

*   `POST /api/file/2/files/synchronous/start`: Start Sync Session (`SynchronousStartLocalDTO` -> `SynchronousStartLocalVO`)
*   `POST /api/file/2/files/synchronous/end`: End Sync Session (`SynchronousEndLocalDTO` -> `SynchronousEndLocalVO`)

### Device File Operations

Endpoints for listing, querying, moving, copying, creating, and deleting synced files and folders.

*   `POST /api/file/2/files/create_folder_v2`: Create Folder (`CreateFolderLocalDTO` -> `CreateFolderLocalVO`)
*   `POST /api/file/2/files/list_folder`: List Folder V2 (`ListFolderLocalDTO` -> `ListFolderLocalVO`)
*   `POST /api/file/3/files/list_folder_v3`: List Folder V3 (`ListFolderV2DTO` -> `ListFolderLocalVO`)
*   `POST /api/file/3/files/delete_folder_v3`: Delete Folder/File (`DeleteFolderLocalDTO` -> `DeleteFolderLocalVO`)
*   `POST /api/file/3/files/query_v3`: Query File (`FileQueryLocalDTO` -> `FileQueryLocalVO`)
*   `POST /api/file/3/files/query/by/path_v3`: Query File by Path (`FileQueryByPathLocalDTO` -> `FileQueryByPathLocalVO`)
*   `POST /api/file/3/files/move_v3`: Move File (`FileMoveLocalDTO` -> `FileMoveLocalVO`)
*   `POST /api/file/3/files/copy_v3`: Copy File (`FileCopyLocalDTO` -> `FileCopyLocalVO`)
*   `POST /api/file/2/users/get_space_usage`: Check Capacity (`CapacityLocalDTO` -> `CapacityLocalVO`)

### Device Upload/Download

Endpoints for initiating device uploads, confirming completed transfers, and requesting signed download URLs.

*   `POST /api/file/3/files/upload/apply`: Upload Request (`FileUploadApplyLocalDTO` -> `FileUploadApplyLocalVO`)
*   `POST /api/file/2/files/upload/finish`: Upload Finish (`FileUploadFinishLocalDTO` -> `FileUploadFinishLocalVO`)
*   `POST /api/file/3/files/download_v3`: Download Request (`FileDownloadLocalDTO` -> `FileDownloadLocalVO`)

### File Conversion

Endpoints for converting `.note` and marked PDF files to PDF or PNG exports.

*   `POST /api/file/note/to/pdf`: Convert Note to PDF (`PdfDTO` -> `NoteToPdfVO`)
*   `POST /api/file/note/to/png`: Convert Note to PNG (`PngDTO` -> `NoteToPngVO`)
*   `POST /api/file/pdfwithmark/to/pdf`: Convert PDF with Mark to PDF

### Connectivity

Endpoints for checking server reachability from devices.

*   `GET /api/file/query/server`: Ping Server

---

## Schedule, Summaries & Sharing (`supernote.models.schedule`, `supernote.models.summary`)

### Sharing

Endpoints for creating file share links and records.

*   `POST /api/file/share/record/add`: Create Share Record

### Scheduling & Calendar (`supernote.models.schedule`)

Endpoints for managing task lists, tasks, and custom sort orders. See `supernote.models.schedule` and `supernote.guides.schedule_api` for the complete Schedule API and RFC 5545 `.ics` feed specification.

*   **Groups:**
    *   `POST /api/file/schedule/group`: Add Group (`AddScheduleTaskGroupDTO` -> `AddScheduleTaskGroupVO`)
    *   `PUT /api/file/schedule/group`: Update Group (`UpdateScheduleTaskGroupDTO`)
    *   `DELETE /api/file/schedule/group/{taskListId}`: Delete Group
    *   `POST /api/file/schedule/group/clear`: Clear Group (`ClearScheduleTaskGroupDTO`)
    *   `GET /api/file/schedule/group/{taskListId}`: Get Group (`GetScheduleTaskGroupVO`)
    *   `POST /api/file/schedule/group/all`: Get All Groups (`ScheduleTaskGroupDTO` -> `ScheduleTaskGroupVO`)
*   **Tasks:**
    *   `POST /api/file/schedule/task`: Add Task (`AddScheduleTaskDTO` -> `AddScheduleTaskVO`)
    *   `PUT /api/file/schedule/task`: Update Task (`UpdateScheduleTaskDTO` -> `UpdateScheduleTaskVO`)
    *   `PUT /api/file/schedule/task/list`: Batch Update Tasks (`UpdateScheduleTaskListDTO`)
    *   `DELETE /api/file/schedule/task/{taskId}`: Delete Task
    *   `GET /api/file/schedule/task/{taskId}`: Get Task (`ScheduleTaskVO`)
    *   `POST /api/file/schedule/task/all`: Get All Tasks (`ScheduleTaskDTO` -> `ScheduleTaskAllVO`)
*   **Sorting:**
    *   `POST /api/file/schedule/sort`: Add Sort (`ScheduleSortDTO`)
    *   `PUT /api/file/schedule/sort`: Update Sort (`UpdateScheduleSortDTO`)
    *   `DELETE /api/file/schedule/sort/{taskListId}`: Delete Sort
    *   `POST /api/file/query/schedule/sort`: Get Sort (`QueryScheduleSortDTO` -> `ScheduleSortVO`)

### Summaries & Tags (`supernote.models.summary`)

Endpoints for managing document summaries, digests, tags, and summary blobs. See `supernote.models.summary` and `supernote.guides.summary_api` for detailed workflow documentation.

*   `POST /api/file/add/summary/tag`: Add Tag (`AddSummaryTagDTO` -> `AddSummaryTagVO`)
*   `PUT /api/file/update/summary/tag`: Update Tag (`UpdateSummaryTagDTO`)
*   `DELETE /api/file/delete/summary/tag`: Delete Tag (`DeleteSummaryTagDTO`)
*   `GET /api/file/query/summary/tag`: Query Tags (`QuerySummaryTagVO`)
*   `POST /api/file/add/summary`: Add Summary (`AddSummaryDTO` -> `AddSummaryVO`)
*   `PUT /api/file/update/summary`: Update Summary (`UpdateSummaryDTO`)
*   `DELETE /api/file/delete/summary`: Delete Summary (`DeleteSummaryDTO`)
*   `POST /api/file/query/summary`: Query Summaries (`QuerySummaryDTO` -> `QuerySummaryVO`)
*   `POST /api/file/download/summary`: Download Summary (`DownloadSummaryDTO` -> `DownloadSummaryVO`)
*   `POST /api/file/upload/apply/summary`: Upload Summary (`UploadSummaryApplyDTO` -> `UploadSummaryApplyVO`)

---

## Server Extensions, API Keys & Semantic Search (`supernote.models.extended`)

Models in `supernote.models.extended` power the custom `/api/extended/*` endpoints on the self-hosted server, consumed by `supernote.client.extended.ExtendedClient` and `supernote.client.admin.AdminClient`. See `supernote.guides.note_processing_design` for the background pipeline architecture.

* **Hybrid Semantic Search** (`POST /api/extended/search`): `WebSearchRequestDTO` (`query`, `top_n`, `name_filter`, `date_after`, `date_before`) -> `WebSearchResponseVO` (list of `SearchResultVO` with stringified `file_id`, `file_name`, `page_index`, `page_id`, `score`, `text_preview`, `date`).
* **OCR Page Transcripts** (`POST /api/extended/transcript`): `WebTranscriptRequestDTO` (stringified `file_id`, optional `start_index` / `end_index`) -> `WebTranscriptResponseVO` (`pages: list[PageTranscriptVO]`).
* **Web Summaries, Structured Notebook Metadata & Note Cover Previews**:
  * `POST /api/extended/file/summary/list`: `WebSummaryListRequestDTO` -> `WebSummaryListVO`
  * `POST /api/extended/file/note/cover`: `WebNoteCoverRequestDTO` -> `WebNoteCoverVO`
  * `POST /api/extended/file/note/metadata`: `WebNoteMetadataRequestDTO` -> `WebNoteMetadataVO` (`file_id`, `equipment`, `total_pages`, `keywords`, `titles: list[NoteTitleVO]`, `links: list[NoteLinkVO]`, `pages: list[NotePageMetadataVO]`)
* **Static Bearer API Keys**:
  * `POST /api/extended/keys`: `CreateApiKeyDTO` (`name`, `expires_in_days`) -> `CreateApiKeyResponseVO` (`id`, `name`, `key`, `created_at`, `expires_at`)
  * `GET /api/extended/keys`: `ApiKeyListResponseVO` (`keys: list[ApiKeyVO]`)
  * `DELETE /api/extended/keys/{keyId}`: `BaseResponse`
* **OAuth Client Grants**:
  * `GET /api/extended/oauth/grants`: `OAuthGrantListResponseVO` (`grants: list[OAuthGrantVO]`: `id`, `client_id`, `scopes`, `created_at`, `expires_at`, `last_used_at`)
  * `DELETE /api/extended/oauth/grants/{grantId}`: `BaseResponse`
* **AI Configuration & Processing Tasks**:
  * `GET /api/extended/ai/status`: `WebAiStatusVO` (`has_api_key`, `ocr_enabled`, `ocr_model`, `summary_enabled`, `summary_model`, `vector_search_enabled`, `embedding_model`)
  * `POST /api/extended/file/processing/status`: `FileProcessingStatusDTO` -> `FileProcessingStatusVO`
  * `GET /api/extended/system/tasks`: `SystemTaskListVO` (`tasks: list[SystemTaskVO]`)

---

## Incremental Domain Event Feed (`supernote.models.events`)

Models in `supernote.models.events` define the wire contract for `GET /api/extended/events` and `supernote.client.events.EventsClient`:

* **Enumerations**:
  * `DomainEventType`: `vfs.created`, `vfs.content_updated`, `vfs.moved`, `vfs.copied`, `vfs.deleted`, `note.pages_delta`, `note.page_transcribed`, `note.processing_completed`, `note.processing_failed`, `schedule.task_created`, `schedule.task_updated`, `schedule.task_deleted`, `summary.upserted`, `summary.deleted`
  * `DomainEntityType`: `file`, `note_page`, `schedule_task`, `summary`
* **Request & Response Envelopes**:
  * `EventFeedRequestDTO` (`sync_token`, `event_types`, `file_id`, `limit`)
  * `DomainEventVO` (`seq`, `timestamp`, `event_type`, `actor`, `entity_type`, `entity_id`, `related_file_id`, `payload`)
  * `EventFeedListVO` (`events: list[DomainEventVO]`, `next_sync_token`, `has_more`)

---

## Outbound Webhooks (`supernote.models.webhook`)

Models in `supernote.models.webhook` define the JSON payloads dispatched by `supernote.server.components.webhooks.service.WebhookService` when a `.note` file completes synchronization or background AI processing:

* **Event Constants**: `EVENT_NOTE_SYNC_COMPLETED` (`"note.sync_completed"`) and `EVENT_NOTE_PROCESSING_COMPLETED` (`"note.processing_completed"`)
* **Payloads**: `WebhookPayload` (`event`, `timestamp`, `user_id`, and `file: WebhookFileVO` containing `id`, `name`, and `path`)

See `supernote.guides.webhooks_and_integrations` for HMAC-SHA256 signature verification (`X-Supernote-Signature`) and consumer examples.

---

## Real-Time Socket.IO Events (`supernote.models.socket`)

Models in `supernote.models.socket` define the real-time event protocol between the server's `/socket.io` namespace and connected clients (`supernote.client.socket.SupernoteSocketClient`):

* **Handshake & Authentication**: `SocketHandshakeParams` (`token`, `type`, `random`, `sign`, `equipment_no`)
* **Message Envelope**: `SocketIoClientMessage` (`code: SocketIoMessageCode`, `msg_type: SocketIoMessageType`, `equipment_no`, `data`), `SocketIoEvent`, and `SocketIoAction`
* **Typed Event Payloads**:
  * `FILE-SYN`: `SocketMessageData` (file/folder creation, modification, deletion, and rename notifications)
  * `TASK-SYN`: `SocketTaskMessageData` (schedule task and group synchronization prompts)
  * `DIGEST-SYN`: `SocketDigestMessageData` (summary/digest synchronization notifications)

---

## System, Equipment & Object Storage (`supernote.models.equipment`, `supernote.models.system`)

### Equipment Management (`supernote.models.equipment`)

Endpoints for activating, binding, unbinding, and querying paired Supernote hardware devices.

*   `POST /api/terminal/user/activateEquipment`: Activate Device (`ActivateEquipmentDTO`)
*   `POST /api/terminal/user/bindEquipment`: Bind Device (`BindEquipmentDTO`)
*   `POST /api/terminal/equipment/unlink`: Unbind Device (`UnbindEquipmentDTO`)
*   `POST /api/equipment/bind/status`: Check Bind Status
*   `POST /api/equipment/query/user/equipment/deleteApi`: Query Equipment List (`UserEquipmentDTO` -> `UserEquipmentVO`)
*   `POST /api/equipment/query/by/equipmentno`: Query by Serial No (`QueryEquipmentDTO`)
*   `GET /api/equipment/query/by/{userId}`: Query by User ID

### OSS Object Storage & System Maintenance (`supernote.models.system`)

Endpoints for signed direct binary uploads, multipart uploads, downloads, background queue status, and storage integrity verification.

*   `POST /api/oss/generate/upload/url`: Get Upload URL
*   `POST /api/oss/upload`: Upload File (`UploadFileVO`)
*   `POST /api/oss/upload/part`: Multipart Upload (`FileChunkParams` -> `FileChunkVO`)
*   `POST /api/oss/generate/download/url`: Get Download URL
*   `GET /api/admin/queue/status`: Processor Queue Status (`QueueStatusVO`)
*   `POST /api/admin/integrity`: Two-Way Storage Integrity Verification (`IntegrityReportVO`)
