"""Data models for self-hosted server intelligence extensions (`/api/extended/*`).

This module defines request DTOs and response VOs for features specific to the self-hosted Supernote
server, including hybrid semantic search (`WebSearchRequestDTO`, `WebSearchResponseVO`,
`SearchResultChunkVO`), page OCR transcripts (`WebTranscriptRequestDTO`, `WebTranscriptResponseVO`,
`PageTranscriptVO`), AI summary listings (`WebSummaryListRequestDTO`, `WebSummaryListVO`), and
background task inspection (`FileProcessingStatusDTO`, `FileProcessingStatusVO`, `SystemTaskVO`,
`SystemTaskListVO`). Consumed by `supernote.client.extended.ExtendedClient`.
"""

from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from supernote.models.base import BaseResponse, ProcessingStatus
from supernote.models.summary import SummaryItem


def _serialize_str_list(values: list[int]) -> list[str]:
    return [str(v) for v in values]


@dataclass
class SummaryTranscriptVO(DataClassJSONMixin):
    """Server-side OCR transcript for a Digest summary's handwritten `.mark` annotation.

    Unlike `SummaryItem` (which mirrors the Supernote device sync protocol and stores the
    highlighted excerpt, typed comment, and raw `.mark` blob reference), this VO holds
    server-generated handwriting OCR output (`f_summary_transcript`). Returning it in a
    separate `WebSummaryListVO.transcripts` map keeps `SummaryItem` wire-compatible with
    Supernote tablets while letting extended Web UI and automation clients read OCR text
    keyed by string `summaryId`.
    """

    summary_id: int = field(metadata=field_options(alias="summaryId", serialize=str))
    """Summary database ID."""

    handwrite_md5: str = field(metadata=field_options(alias="handwriteMD5"))
    """MD5 hash of the `.mark` handwriting blob that produced this transcript."""

    text: str
    """Extracted handwriting OCR text."""

    model_id: str | None = field(metadata=field_options(alias="modelId"), default=None)
    """Identifier of the OCR model that produced this transcript."""

    update_time: int | None = field(
        metadata=field_options(alias="updateTime"), default=None
    )
    """Last update timestamp in milliseconds."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebSummaryListRequestDTO(DataClassJSONMixin):
    """Request DTO for listing summaries with optional file, category, and pagination filters."""

    file_id: int | None = field(
        metadata=field_options(alias="fileId", serialize=str), default=None
    )
    """Optional ID of the file to filter summaries for; omit to list across all files."""

    parent_unique_identifier: str | None = field(
        metadata=field_options(alias="parentUniqueIdentifier"), default=None
    )
    """Optional category/group UUID to filter summaries by."""

    page: int | None = None
    """Optional 1-indexed page number when paginating."""

    size: int | None = None
    """Optional page size when paginating."""

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True


@dataclass
class WebSummaryListVO(BaseResponse):
    """Response VO for listing summaries (Web Extension).

    Used by: POST /api/extended/file/summary/list
    """

    summary_do_list: list[SummaryItem] = field(
        metadata=field_options(alias="summaryDOList"), default_factory=list
    )
    """List of summary items found."""

    total_records: int = field(metadata=field_options(alias="totalRecords"), default=0)
    """Total count of summaries returned."""

    transcripts: dict[str, SummaryTranscriptVO] = field(default_factory=dict)
    """Map of string `summaryId` to its current handwritten annotation OCR transcript."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SystemTaskVO(DataClassJSONMixin):
    """VO for a system processing task.

    Used by: GET /api/extended/system/tasks
    """

    id: int = field(metadata=field_options(serialize=str))
    """The unique ID of the system task."""

    file_id: int | None = field(metadata=field_options(alias="fileId", serialize=str))
    """The ID of the file associated with this task (populated for file-scoped tasks)."""

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

    file_name: str | None = field(
        metadata=field_options(alias="fileName"), default=None
    )
    """Human-readable notebook filename resolved from UserFileDO."""

    page_index: int | None = field(
        metadata=field_options(alias="pageIndex"), default=None
    )
    """0-based page index resolved from NotePageContentDO for page-scoped tasks."""

    entity_type: str | None = field(
        metadata=field_options(alias="entityType"), default=None
    )
    """Entity kind targeted by this task (e.g. 'file', 'summary')."""

    entity_id: int | None = field(
        metadata=field_options(alias="entityId", serialize=str), default=None
    )
    """Numeric ID of the target entity."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SystemTaskListVO(BaseResponse):
    """Response VO for listing system tasks.

    Used by: GET /api/extended/system/tasks
    """

    tasks: list[SystemTaskVO] = field(default_factory=list)
    """List of recent system tasks (active and failed prioritized first)."""

    paused: bool = False
    """Whether the background processing queue is currently paused."""

    queue_size: int = field(metadata=field_options(alias="queueSize"), default=0)
    """Number of active/queued files currently in flight for this user."""

    processing_file_ids: list[int] = field(
        metadata=field_options(
            alias="processingFileIds", serialize=_serialize_str_list
        ),
        default_factory=list,
    )
    """IDs of files belonging to this user that are currently queued or processing."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class RetrySystemTasksDTO(DataClassJSONMixin):
    """Request DTO for retrying failed processing tasks for a single file or all user files.

    Used by: POST /api/extended/system/tasks/retry
    """

    file_id: int | None = field(
        metadata=field_options(
            alias="fileId",
            serialize=lambda v: str(v) if v is not None else None,
        ),
        default=None,
    )
    """Optional notebook file ID to scope the retry to a single file."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class RetrySystemTasksVO(BaseResponse):
    """Response VO for retrying failed processing tasks.

    Used by: POST /api/extended/system/tasks/retry
    """

    retried_file_ids: list[int] = field(
        metadata=field_options(alias="retriedFileIds", serialize=_serialize_str_list),
        default_factory=list,
    )
    """IDs of active notebooks whose failed checkpoints were cleared and re-queued."""

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
    titles: dict[str, str] = field(default_factory=dict)
    """Transcribed title text keyed by `<TITLEBITMAP>` MD5."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ApiKeyVO(DataClassJSONMixin):
    """VO representing static Bearer API key metadata.

    Used by: GET /api/extended/keys
    """

    id: str
    name: str
    key_prefix: str = field(metadata=field_options(alias="keyPrefix"))
    created_at: int = field(metadata=field_options(alias="createdAt"))
    last_used_at: int | None = field(
        metadata=field_options(alias="lastUsedAt"), default=None
    )
    expires_at: int | None = field(
        metadata=field_options(alias="expiresAt"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class CreateApiKeyDTO(DataClassJSONMixin):
    """Request DTO to create a new static Bearer API key.

    Used by: POST /api/extended/keys
    """

    name: str
    expires_in_days: int | None = field(
        metadata=field_options(alias="expiresInDays"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class CreateApiKeyResponseVO(BaseResponse):
    """Response VO after creating a new static Bearer API key.

    Used by: POST /api/extended/keys
    """

    id: str = ""
    name: str = ""
    key: str = ""
    created_at: int = field(metadata=field_options(alias="createdAt"), default=0)
    expires_at: int | None = field(
        metadata=field_options(alias="expiresAt"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ApiKeyListResponseVO(BaseResponse):
    """Response VO listing static Bearer API keys.

    Used by: GET /api/extended/keys
    """

    keys: list[ApiKeyVO] = field(default_factory=list)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class OAuthGrantVO(DataClassJSONMixin):
    """VO representing an OAuth client the user has authorized.

    Used by: GET /api/extended/oauth/grants
    """

    id: str
    client_id: str = field(metadata=field_options(alias="clientId"))
    """Client ID Metadata Document URL of the client that requested access."""

    scopes: list[str]
    created_at: int = field(metadata=field_options(alias="createdAt"))
    expires_at: int = field(metadata=field_options(alias="expiresAt"))
    last_used_at: int | None = field(
        metadata=field_options(alias="lastUsedAt"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class OAuthGrantListResponseVO(BaseResponse):
    """Response VO listing authorized OAuth clients.

    Used by: GET /api/extended/oauth/grants
    """

    grants: list[OAuthGrantVO] = field(default_factory=list)

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


@dataclass
class WebNoteMetadataRequestDTO(DataClassJSONMixin):
    """Request DTO for retrieving structured notebook and page metadata."""

    file_id: int = field(metadata=field_options(alias="fileId", serialize=str))
    """The unique ID of the notebook."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class NoteTitleVO(DataClassJSONMixin):
    """Heading/outline entry anchored to a notebook page, in reading order."""

    page_index: int = field(metadata=field_options(alias="pageIndex"))
    level: int = 1
    style: str | None = None
    """Raw `<TITLESTYLE>` code for the background the user picked on the device."""
    rect: list[int] | None = None
    """Title bounding box `[left, top, width, height]` in page pixels."""
    bitmap_md5: str | None = field(
        metadata=field_options(alias="bitmapMd5"), default=None
    )
    """MD5 of the title's handwriting bitmap; changes only when the title is redrawn."""
    image_url: str | None = field(
        metadata=field_options(alias="imageUrl"), default=None
    )
    """Signed URL of the title's handwriting crop PNG, or `None` if it has no bitmap."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class NoteLinkVO(DataClassJSONMixin):
    """Hyperlink entry anchored to a notebook page."""

    page_index: int = field(metadata=field_options(alias="pageIndex"))
    link_type: str = field(metadata=field_options(alias="linkType"))
    target: str | None = None
    target_file_id: int | None = field(
        metadata=field_options(
            alias="targetFileId",
            serialize=lambda v: str(v) if v is not None else None,
        ),
        default=None,
    )
    target_page_index: int | None = field(
        metadata=field_options(alias="targetPageIndex"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class NotePageMetadataVO(DataClassJSONMixin):
    """Per-page structural metadata, blank/star flags, and keywords."""

    page_index: int = field(metadata=field_options(alias="pageIndex"))
    page_id: str = field(metadata=field_options(alias="pageId"))
    date: str | None = None
    style: str | None = None
    is_blank: bool = field(metadata=field_options(alias="isBlank"), default=False)
    has_five_star: bool = field(
        metadata=field_options(alias="hasFiveStar"), default=False
    )
    keywords: list[str] = field(default_factory=list)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebNoteMetadataVO(BaseResponse):
    """Response VO for structured notebook and per-page metadata.

    Used by: POST /api/extended/file/note/metadata
    """

    file_id: int = field(
        metadata=field_options(alias="fileId", serialize=str), default=0
    )
    equipment: str | None = None
    total_pages: int = field(metadata=field_options(alias="totalPages"), default=0)
    keywords: dict[str, list[int]] = field(default_factory=dict)
    titles: list[NoteTitleVO] = field(default_factory=list)
    links: list[NoteLinkVO] = field(default_factory=list)
    pages: list[NotePageMetadataVO] = field(default_factory=list)

    class Config(BaseConfig):
        serialize_by_alias = True
