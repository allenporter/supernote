# API Data Models for Supernote (Private) Cloud

This package (`supernote.models`) defines the shared wire-format Data Transfer Objects (DTOs) and Value Objects (VOs) used by both the `supernote.client` SDK and the `supernote.server` self-hosted Private Cloud implementation.

> [!NOTE]
> While these models match the official Supernote Private Cloud protocol, they are designed for self-hosted servers and local tooling rather than placing automated load on Ratta's hosted public cloud.

---

## Serialization Architecture

All request DTOs and response VOs are Python `@dataclass` models backed by `mashumaro` (`DataClassJSONMixin` / `DataClassORJSONMixin` compatible):

* **CamelCase Wire Aliasing**: Python fields use `snake_case` with `field(metadata=field_options(alias="camelCase"))` and `serialize_by_alias = True` in `BaseConfig` so serialized JSON matches the exact camelCase keys expected by Supernote hardware firmware and the web UI.
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
| `supernote.models.extended` | Self-hosted semantic search, transcripts, and task status | `WebSearchRequestDTO`, `WebSearchResponseVO`, `WebTranscriptResponseVO`, `FileProcessingStatusVO` |
| `supernote.models.webhook` | Outbound HMAC-signed webhook event payloads | `WebhookPayload`, `WebhookFileVO`, `EVENT_NOTE_SYNC_COMPLETED`, `EVENT_NOTE_PROCESSING_COMPLETED` |
| `supernote.models.socket` | Real-time Socket.IO events (`FILE-SYN`, `TASK-SYN`, `DIGEST-SYN`) | `SocketHandshakeParams`, `SocketIoClientMessage`, `SocketMessageData`, `SocketTaskMessageData` |
| `supernote.models.equipment` | Hardware device activation and binding | `ActivateEquipmentDTO`, `BindEquipmentDTO`, `UnbindEquipmentDTO`, `UserEquipmentVO` |
| `supernote.models.system` | OSS multipart chunks, queue status, and storage integrity | `FileChunkVO`, `UploadFileVO`, `QueueStatusVO`, `IntegrityReportVO`, `ReferenceSysParamDTO` |

---

## 1. Authentication & User Management (`supernote.models.auth`, `supernote.models.user`)

Models in `supernote.models.auth` and `supernote.models.user` back account login, challenge-response hashing, SMS verification, and user profile management (handled on the server by `supernote.server.routes.auth` and `supernote.server.routes.user`, and consumed by `supernote.client.login_client.LoginClient` and `supernote.client.admin.AdminClient`).

### Login & Token Validation
* `POST /api/official/user/query/random/code` — Request challenge nonce (`RandomCodeDTO` -> `RandomCodeVO`)
* `POST /api/official/user/account/login/new` — Account password login (`LoginDTO` -> `LoginVO`)
* `POST /api/official/user/account/login/equipment` — Hardware device login (`LoginDTO` -> `LoginVO`)
* `POST /api/user/sms/validcode` & `POST /api/user/sms/login` — SMS code request & login (`SendSmsDTO` -> `SendSmsVO`, `SmsLoginDTO` -> `SmsLoginVO`)
* `POST /api/user/query/token` — Validate active JWT token (`QueryTokenDTO` -> `QueryTokenVO`)
* `POST /api/user/logout` — Invalidate session (`BaseResponse`)

### User Profile, Registration & Security
* `POST /api/user/register` — Register user (`UserRegisterDTO` -> `BaseResponse`)
* `POST /api/user/account/clear` — Permanently delete user account and all cloud data (`BaseResponse`)
* `POST /api/user/query` & `GET /api/user/query/user/{userId}` — Query user profile (`UserQueryVO`, `UserQueryByIdVO`)
* `POST /api/user/update` — Update profile attributes (`UpdateUserDTO` -> `BaseResponse`)
* `PUT /api/user/password` & `POST /api/official/user/retrieve/password` — Change or reset password (`UpdatePasswordDTO`, `RetrievePasswordDTO`)
* `PUT /api/user/email` — Update email address (`UpdateEmailDTO` -> `BaseResponse`)

---

## 2. Web File Management (`supernote.models.file_web`, `supernote.models.file_common`)

Models in `supernote.models.file_web` and `supernote.models.file_common` support the ID-based directory hierarchy, recycle bin, and 3-step file uploads used by the browser UI and `supernote.client.web.WebClient`.

* **Directory & Path Queries**:
  * `POST /api/file/list/query` (`FileListQueryDTO` -> `FileListQueryVO` containing `UserFileVO` items)
  * `POST /api/file/folder/list/query` (`FolderListQueryDTO` -> `FolderListQueryVO` containing `FolderVO` items)
  * `POST /api/file/path/query` (`FilePathQueryDTO` -> `FilePathQueryVO`)
  * `POST /api/file/capacity/query` (`CapacityVO`)
* **Mutations & Search**:
  * `POST /api/file/folder/add` (`FolderAddDTO`), `POST /api/file/rename` (`FileReNameDTO`), `POST /api/file/move` & `POST /api/file/copy` (`FileMoveAndCopyDTO`), `POST /api/file/delete` (`FileDeleteDTO`)
  * `POST /api/file/label/list/search` (`FileLabelSearchDTO` -> `FileLabelSearchVO`)
* **Recycle Bin**:
  * `POST /api/file/recycle/list/query` (`RecycleFileListDTO` -> `RecycleFileListVO`)
  * `POST /api/file/recycle/revert`, `POST /api/file/recycle/delete` (`RecycleFileDTO`), `POST /api/file/recycle/clear`
* **Upload & Download**:
  * `POST /api/file/upload/apply` (`FileUploadApplyDTO` -> `FileUploadApplyLocalVO`)
  * `POST /api/file/upload/finish` (`FileUploadFinishDTO` -> `BaseResponse`)
  * `POST /api/file/download/url` (`FileDownloadDTO` -> `FileDownloadUrlVO`)

---

## 3. Hardware Device Synchronization (`supernote.models.file_device`)

Models in `supernote.models.file_device` implement the V2/V3 path- and ID-based synchronization protocol used by Supernote tablets and `supernote.client.device.DeviceClient`.

* **Sync Session Locks**:
  * `POST /api/file/2/files/synchronous/start` (`SynchronousStartLocalDTO` -> `SynchronousStartLocalVO`)
  * `POST /api/file/2/files/synchronous/end` (`SynchronousEndLocalDTO` -> `SynchronousEndLocalVO`)
* **V2/V3 File & Folder Operations**:
  * `POST /api/file/2/files/list_folder` & `POST /api/file/3/files/list_folder_v3` (`ListFolderLocalDTO`, `ListFolderV2DTO` -> `ListFolderLocalVO` with `EntriesVO`)
  * `POST /api/file/2/files/create_folder_v2` (`CreateFolderLocalDTO` -> `CreateFolderLocalVO`)
  * `POST /api/file/3/files/delete_folder_v3` (`DeleteFolderLocalDTO` -> `DeleteFolderLocalVO`)
  * `POST /api/file/3/files/query_v3` (`FileQueryLocalDTO` -> `FileQueryLocalVO`)
  * `POST /api/file/3/files/query/by/path_v3` (`FileQueryByPathLocalDTO` -> `FileQueryByPathLocalVO`)
  * `POST /api/file/3/files/move_v3` (`FileMoveLocalDTO` -> `FileMoveLocalVO`) & `POST /api/file/3/files/copy_v3` (`FileCopyLocalDTO` -> `FileCopyLocalVO`)
  * `POST /api/file/2/users/get_space_usage` (`CapacityLocalDTO` -> `CapacityLocalVO`)
* **Device Upload, Download & Conversion**:
  * `POST /api/file/3/files/upload/apply` (`FileUploadApplyLocalDTO` -> `FileUploadApplyLocalVO`)
  * `POST /api/file/2/files/upload/finish` (`FileUploadFinishLocalDTO` -> `FileUploadFinishLocalVO`)
  * `POST /api/file/3/files/download_v3` (`FileDownloadLocalDTO` -> `FileDownloadLocalVO`)
  * `POST /api/file/note/to/png` (`PngDTO` -> `NoteToPngVO`) & `POST /api/file/note/to/pdf` (`PdfDTO` -> `NoteToPdfVO`)

---

## 4. Schedule & To-Do Tasks (`supernote.models.schedule`)

Models in `supernote.models.schedule` represent task groups (`ScheduleTaskGroupItem`) and tasks (`ScheduleTaskInfo`), consumed by `supernote.client.schedule.ScheduleClient`. See `supernote.guides.schedule_api` for the complete Schedule API and `.ics` feed specification.

* **Task Groups**: `AddScheduleTaskGroupDTO` -> `AddScheduleTaskGroupVO`, `UpdateScheduleTaskGroupDTO`, `ClearScheduleTaskGroupDTO`, `ScheduleTaskGroupDTO` -> `ScheduleTaskGroupVO`, `GetScheduleTaskGroupVO`
* **Tasks**: `AddScheduleTaskDTO` -> `AddScheduleTaskVO`, `UpdateScheduleTaskDTO` -> `UpdateScheduleTaskVO`, `UpdateScheduleTaskListDTO` (batch updates), `ScheduleTaskDTO` -> `ScheduleTaskAllVO`, `ScheduleTaskVO`
* **Sort Ordering**: `ScheduleSortDTO`, `UpdateScheduleSortDTO`, `QueryScheduleSortDTO` -> `ScheduleSortVO`

---

## 5. Summaries & Tags (`supernote.models.summary`)

Models in `supernote.models.summary` represent device-authored handwritten digests and server-synthesized AI summaries (`SummaryItem`), summary groups (`SummaryGroupItem`), and tags (`SummaryTagItem`), consumed by `supernote.client.summary.SummaryClient`. See `supernote.guides.summary_api` for detailed workflow documentation.

* **Tags**: `AddSummaryTagDTO` -> `AddSummaryTagVO`, `UpdateSummaryTagDTO`, `DeleteSummaryTagDTO`, `QuerySummaryTagVO`
* **Summary Groups**: `AddSummaryGroupDTO` -> `AddSummaryGroupVO`, `UpdateSummaryGroupDTO`, `DeleteSummaryGroupDTO`, `QuerySummaryGroupDTO` -> `QuerySummaryGroupVO`, `QuerySummaryMD5HashVO`
* **Summaries**: `AddSummaryDTO` -> `AddSummaryVO`, `UpdateSummaryDTO`, `DeleteSummaryDTO`, `QuerySummaryDTO` -> `QuerySummaryVO`, `QuerySummaryByIdVO`, `UploadSummaryApplyDTO` -> `UploadSummaryApplyVO`, `DownloadSummaryDTO` -> `DownloadSummaryVO`

---

## 6. Server Extensions & Semantic Search (`supernote.models.extended`)

Models in `supernote.models.extended` power the custom `/api/extended/*` intelligence endpoints on the self-hosted server, consumed by `supernote.client.extended.ExtendedClient` and `supernote.client.admin.AdminClient`. See `supernote.guides.note_processing_design` for the background pipeline architecture.

* **Hybrid Semantic Search** (`POST /api/extended/search`): `WebSearchRequestDTO` (query text, `top_k`, `name_filter`, `date_after`, `date_before`) -> `WebSearchResponseVO` (list of `SearchResultChunkVO` with `file_id`, `file_path`, `page_index`, `page_id`, `score`, `text_preview`, `UpdatedDate`)
* **OCR Page Transcripts** (`POST /api/extended/file/transcript`): `WebTranscriptRequestDTO` (optional `start_index` / `end_index`) -> `WebTranscriptResponseVO` (`transcript` and per-page `PageTranscriptVO` list)
* **Web Summaries** (`POST /api/extended/file/summary/list`): `WebSummaryListRequestDTO` -> `WebSummaryListVO`
* **Processing Status & System Tasks**: `FileProcessingStatusDTO` -> `FileProcessingStatusVO` (`POST /api/extended/file/status`) and `SystemTaskListVO` (`GET /api/extended/system/tasks`)

---

## 7. Outbound Webhooks (`supernote.models.webhook`)

Models in `supernote.models.webhook` define the JSON payloads dispatched by `supernote.server.services.webhook.WebhookService` when a `.note` file completes synchronization or background AI processing:

* **Event Constants**: `EVENT_NOTE_SYNC_COMPLETED` (`"note.sync_completed"`) and `EVENT_NOTE_PROCESSING_COMPLETED` (`"note.processing_completed"`)
* **Payloads**: `WebhookPayload` (`event`, `timestamp`, `user_id`, and `file: WebhookFileVO` containing `id`, `name`, and `path`)

See `supernote.guides.webhooks_and_integrations` for HMAC-SHA256 signature verification (`X-Supernote-Signature`) and consumer examples.

---

## 8. Real-Time Socket.IO Events (`supernote.models.socket`)

Models in `supernote.models.socket` define the real-time event protocol between the server's `/socket.io` namespace and connected clients (`supernote.client.socket.SupernoteSocketClient`):

* **Handshake & Authentication**: `SocketHandshakeParams` (`token`, `timeStamp`, `equipment`, `equipmentNo`, `userId`, `version`, `sign`)
* **Message Envelope**: `SocketIoClientMessage` (`code: SocketIoMessageCode`, `msg_type: SocketIoMessageType`, `equipment_no`, `data`), `SocketIoEvent`, and `SocketIoAction`
* **Typed Event Payloads**:
  * `FILE-SYN`: `SocketMessageData` (file/folder creation, modification, deletion, and rename notifications)
  * `TASK-SYN`: `SocketTaskMessageData` (schedule task and group synchronization prompts)
  * `DIGEST-SYN`: `SocketDigestMessageData` (summary/digest synchronization notifications)

---

## 9. Equipment & System Infrastructure (`supernote.models.equipment`, `supernote.models.system`)

* **Equipment Management (`supernote.models.equipment`)**: Hardware activation and binding DTOs/VOs (`ActivateEquipmentDTO`, `BindEquipmentDTO`, `UnbindEquipmentDTO`, `QueryEquipmentDTO`, `UserEquipmentDTO` -> `UserEquipmentVO`).
* **System, OSS & Integrity (`supernote.models.system`)**: Local OSS single/multipart upload models (`UploadFileVO`, `FileChunkParams`, `FileChunkVO`), background processor queue status (`QueueStatusVO`), and two-way storage integrity reports (`IntegrityReportVO`, `MissingBlobVO`, `SizeMismatchVO`, `OrphanFileVO`).
