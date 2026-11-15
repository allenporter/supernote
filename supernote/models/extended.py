"""Module for server-specific extension models.

These are for APIs that are not part of the standard API offering, specific
to our new server.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from supernote.models.base import BaseResponse, ProcessingStatus
from supernote.models.summary import SummaryItem


def _serialize_str_list(values: list[int]) -> list[str]:
    return [str(v) for v in values]


@dataclass
class WebSummaryListRequestDTO(DataClassJSONMixin):
    """Request DTO for listing summaries by file ID (Web Extension)."""

    file_id: int = field(metadata=field_options(alias="fileId", serialize=str))
    """The ID of the file to list summaries for."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebSummaryListVO(BaseResponse):
    """Response VO for listing summaries (Web Extension).

    Used by: POST /api/extended/file/summary/list
    """

    summary_do_list: list[SummaryItem] = field(
        metadata=field_options(alias="summaryDOList"), default_factory=list
    )
    """List of summary items found for the file."""

    total_records: int = field(metadata=field_options(alias="totalRecords"), default=0)
    """Total count of summaries returned."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SystemTaskVO(DataClassJSONMixin):
    """VO for a system processing task.

    Used by: GET /api/extended/system/tasks
    """

    id: int = field(metadata=field_options(serialize=str))
    """The unique ID of the system task."""

    file_id: int = field(metadata=field_options(alias="fileId", serialize=str))
    """The ID of the file associated with this task."""

    task_type: str = field(metadata=field_options(alias="taskType"))
    """The type of task (e.g. 'OCR', 'SUMMARY')."""

    key: str
    """The specific key for the task (e.g. 'page_1', 'global')."""

    status: ProcessingStatus
    """The current status (PENDING, PROCESSING, COMPLETED, FAILED)."""

    retry_count: int = field(metadata=field_options(alias="retryCount"))
    """Number of times the task has been retried."""

    update_time: int = field(metadata=field_options(alias="updateTime"))
    """Timestamp of the last update (ms)."""

    last_error: str | None = field(
        metadata=field_options(alias="lastError"), default=None
    )
    """Error message from the last failure, if any."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SystemTaskListVO(BaseResponse):
    """Response VO for listing system tasks.

    Used by: GET /api/extended/system/tasks
    """

    tasks: list[SystemTaskVO] = field(default_factory=list)
    """List of recent system tasks."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileProcessingStatusDTO(DataClassJSONMixin):
    """Request model for querying processing status of files.

    Used by:
        /api/extended/file/processing/status (POST)
    """

    file_ids: list[int] = field(
        metadata=field_options(alias="fileIds", serialize=_serialize_str_list)
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileProcessingStatusVO(BaseResponse):
    """Response model for file processing status.

    Used by:
        /api/extended/file/processing/status (POST)
    """

    # Map of file_id -> status summary
    # status: PENDING, PROCESSING, COMPLETED, FAILED
    status_map: dict[str, ProcessingStatus] = field(
        metadata=field_options(alias="statusMap"), default_factory=dict
    )


@dataclass
class SearchResultVO(DataClassJSONMixin):
    """VO for a single semantic search result."""

    file_id: int = field(metadata=field_options(alias="fileId", serialize=str))
    file_name: str = field(metadata=field_options(alias="fileName"))
    page_index: int = field(metadata=field_options(alias="pageIndex"))
    page_id: str = field(metadata=field_options(alias="pageId"))
    score: float
    text_preview: str = field(metadata=field_options(alias="textPreview"))
    date: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebSearchRequestDTO(DataClassJSONMixin):
    """Request DTO for semantic search (Web Extension)."""

    query: str
    top_n: int = field(metadata=field_options(alias="topN"), default=5)
    name_filter: str | None = field(
        metadata=field_options(alias="nameFilter"), default=None
    )
    date_after: str | None = field(
        metadata=field_options(alias="dateAfter"), default=None
    )
    date_before: str | None = field(
        metadata=field_options(alias="dateBefore"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebSearchResponseVO(BaseResponse):
    """Response VO for semantic search (Web Extension)."""

    results: list[SearchResultVO] = field(default_factory=list)
    """List of search results."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebTranscriptRequestDTO(DataClassJSONMixin):
    """Request DTO for retrieving a notebook transcript (Web Extension)."""

    file_id: int = field(metadata=field_options(alias="fileId", serialize=str))
    """The unique ID of the notebook."""

    start_index: int | None = field(
        metadata=field_options(alias="startIndex"), default=None
    )
    """Optional 0-based start page index (inclusive)."""

    end_index: int | None = field(
        metadata=field_options(alias="endIndex"), default=None
    )
    """Optional 0-based end page index (inclusive)."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class PageTranscriptVO(DataClassJSONMixin):
    """VO for a single page transcript in a notebook."""

    page_index: int = field(metadata=field_options(alias="pageIndex"))
    page_id: str = field(metadata=field_options(alias="pageId"))
    text: str | None = None
    date: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebTranscriptResponseVO(BaseResponse):
    """Response VO for transcript retrieval (Web Extension)."""

    pages: list[PageTranscriptVO] = field(default_factory=list)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebNoteCoverRequestDTO(DataClassJSONMixin):
    """Request DTO for retrieving a single-page cover preview URL for a notebook."""

    file_id: int = field(metadata=field_options(alias="fileId", serialize=str))
    """The unique ID of the notebook."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebNoteCoverVO(BaseResponse):
    """Response VO for single-page notebook cover preview URL."""

    url: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebAiStatusVO(BaseResponse):
    """Response VO for server AI processing configuration and health status.

    Used by: GET /api/extended/ai/status
    """

    has_api_key: bool = field(metadata=field_options(alias="hasApiKey"), default=False)
    ocr_enabled: bool = field(metadata=field_options(alias="ocrEnabled"), default=False)
    ocr_model: str | None = field(
        metadata=field_options(alias="ocrModel"), default=None
    )
    summary_enabled: bool = field(
        metadata=field_options(alias="summaryEnabled"), default=False
    )
    summary_model: str | None = field(
        metadata=field_options(alias="summaryModel"), default=None
    )
    vector_search_enabled: bool = field(
        metadata=field_options(alias="vectorSearchEnabled"), default=False
    )
    embedding_model: str | None = field(
        metadata=field_options(alias="embeddingModel"), default=None
    )
    model: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


class DomainEventType(StrEnum):
    """Canonical domain event type identifiers recorded in `f_user_event`.

    Each event carries a domain-specific `payload` dictionary on `DomainEventVO`
    describing the mutation delta so incremental consumers can react without
    re-fetching unchanged resources.
    """

    VFS_CREATED = "vfs.created"
    """File or folder created (or copied) in the VFS (`entity_type='file'`).

    Payload keys: `name`, `parent_id`, `full_path`, `is_folder`, `size`, `md5`,
    and optional `copied_from_id`, `copied_from_path`.
    """

    VFS_CONTENT_UPDATED = "vfs.content_updated"
    """Existing VFS file overwritten with new content (`entity_type='file'`).

    Payload keys: `name`, `parent_id`, `full_path`, `size`, `old_md5`, `new_md5`.
    """

    VFS_MOVED = "vfs.moved"
    """File or folder renamed or moved to a new parent (`entity_type='file'`).

    Payload keys: `old_path`, `new_path`, `old_name`, `new_name`,
    `old_parent_id`, `new_parent_id`, `is_folder`, `size`, `md5`.
    """

    VFS_DELETED = "vfs.deleted"
    """File or folder deleted from the VFS (`entity_type='file'`).

    Payload keys: `name`, `parent_id`, `full_path`, `is_folder`, `size`, `md5`.
    """

    NOTE_PAGES_DELTA = "note.pages_delta"
    """Structural page changes detected in a `.note` file (`entity_type='file'`).

    Payload keys: `file_path`, `added_pages`, `modified_pages`, `moved_pages`,
    `deleted_pages`.
    """

    NOTE_PAGE_TRANSCRIBED = "note.page_transcribed"
    """Single notebook page OCR text updated (`entity_type='note_page'`, `entity_id='<file_id>:<page_id>'`).

    Payload keys: `file_path`, `page_id`, `page_index`, `page_modified_ms`,
    `previous_text`, `current_text`.
    """

    NOTE_PROCESSING_COMPLETED = "note.processing_completed"
    """Background processing pipeline finished for a `.note` file (`entity_type='file'`).

    Payload keys: `file_path`, `page_count`.
    """

    NOTE_PROCESSING_FAILED = "note.processing_failed"
    """Background processing pipeline failed for a `.note` file (`entity_type='file'`).

    Payload keys: `file_path`, `module_name`, `page_id`, `error`.
    """

    SCHEDULE_TASK_CREATED = "schedule.task_created"
    """Schedule to-do task created (`entity_type='schedule_task'`).

    Payload keys: `task_id`, `task_list_id`, `title`, `detail`, `status`,
    `due_time`, `links`, `linked_page_id`.
    """

    SCHEDULE_TASK_UPDATED = "schedule.task_updated"
    """Schedule to-do task updated (`entity_type='schedule_task'`).

    Payload keys: `task_id`, `task_list_id`, `title`, `status`,
    `changed_fields`, `linked_page_id`.
    """

    SCHEDULE_TASK_DELETED = "schedule.task_deleted"
    """Schedule to-do task deleted (`entity_type='schedule_task'`).

    Payload keys: `task_id`, `task_list_id`, `title`, `previous_status`,
    `linked_page_id`.
    """

    SUMMARY_UPSERTED = "summary.upserted"
    """Summary or synthesis item created or updated (`entity_type='summary'`).

    Payload keys: `id`, `unique_identifier`, `is_new`, `is_summary_group`,
    `name`, `source_path`, `data_source`, `md5_hash`.
    """

    SUMMARY_DELETED = "summary.deleted"
    """Summary or synthesis item deleted (`entity_type='summary'`).

    Payload keys: `summary_id`, `unique_identifier`, `is_summary_group`.
    """


class DomainEntityType(StrEnum):
    """Canonical target entity categories for domain events."""

    FILE = "file"
    NOTE_PAGE = "note_page"
    SCHEDULE_TASK = "schedule_task"
    SUMMARY = "summary"


@dataclass
class EventFeedRequestDTO(DataClassJSONMixin):
    """Query parameters DTO for polling the per-user domain event feed.

    Used by: GET /api/extended/events
    """

    sync_token: str | None = field(
        metadata=field_options(alias="syncToken"), default=None
    )
    """Opaque checkpoint token returned as `nextSyncToken` by a prior call (`None` to start from the beginning)."""

    event_types: str | None = field(
        metadata=field_options(alias="eventTypes"), default=None
    )
    """Optional comma-separated `DomainEventType` values or namespace globs (`'vfs.*'`, `'note.*'`, `'schedule.*'`, `'summary.*'`)."""

    file_id: int | None = field(
        metadata=field_options(alias="fileId", serialize=str), default=None
    )
    """Optional VFS file ID filter."""

    limit: int = 200
    """Maximum number of events to return (`1..1000`, default `200`)."""

    @property
    def event_type_list(self) -> list[str] | None:
        """Return parsed event type filter strings, or `None` when unset."""
        if not self.event_types:
            return None
        return [
            part.strip() for part in self.event_types.split(",") if part.strip()
        ] or None

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True


@dataclass
class DomainEventVO(DataClassJSONMixin):
    """VO for a single domain event in the per-user event feed.

    Used by: GET /api/extended/events
    """

    seq: str
    """Strictly monotonic 64-bit sequence ID of this event, serialized as a string."""

    timestamp: int
    """Event recording timestamp in UTC epoch milliseconds."""

    event_type: str = field(metadata=field_options(alias="eventType"))
    """Domain event type identifier (see `DomainEventType` in `supernote.models.extended`)."""

    actor: str
    """Originating mutation source (`'user:web'`, `'device:<equipment_no>'`, or `'system:processor'`)."""

    entity_type: str = field(metadata=field_options(alias="entityType"))
    """Target entity category (see `DomainEntityType` in `supernote.models.extended`)."""

    entity_id: str = field(metadata=field_options(alias="entityId"))
    """Stable identifier of the affected entity (e.g. file ID, '<file_id>:<page_index>', task ID)."""

    related_file_id: int | None = field(
        metadata=field_options(alias="relatedFileId", serialize=str), default=None
    )
    """Associated VFS file ID when applicable (serialized as a string on the wire)."""

    payload: dict[str, Any] = field(default_factory=dict)
    """Event-specific delta metadata (paths, hashes, changed fields, OCR text diffs, etc.)."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class EventFeedListVO(BaseResponse):
    """Response VO for querying the per-user domain event feed.

    Used by: GET /api/extended/events
    """

    events: list[DomainEventVO] = field(default_factory=list)
    """Ordered list of domain events occurring after the requested `syncToken`."""

    next_sync_token: str | None = field(
        metadata=field_options(alias="nextSyncToken"), default=None
    )
    """Opaque checkpoint token to pass as `syncToken` on the next request (`None` if no events exist yet)."""

    has_more: bool = field(metadata=field_options(alias="hasMore"), default=False)
    """Whether additional matching events remain beyond the page `limit`."""

    class Config(BaseConfig):
        serialize_by_alias = True
