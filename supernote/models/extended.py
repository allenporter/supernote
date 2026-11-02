"""Module for server-specific extension models.

These are for APIs that are not part of the standard API offering, specific
to our new server.
"""

from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from supernote.models.base import BaseResponse, ProcessingStatus
from supernote.models.summary import SummaryItem


@dataclass
class WebSummaryListRequestDTO(DataClassJSONMixin):
    """Request DTO for listing summaries by file ID (Web Extension)."""

    file_id: int = field(metadata=field_options(alias="fileId"))
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

    id: int
    """The unique ID of the system task."""

    file_id: int = field(metadata=field_options(alias="fileId"))
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

    file_ids: list[int] = field(metadata=field_options(alias="fileIds"))

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

    file_id: int = field(metadata=field_options(alias="fileId"))
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

    file_id: int = field(metadata=field_options(alias="fileId"))
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
    """VO for a single page's OCR transcript in a notebook.

    Used by `POST /api/extended/transcript`, which returns OCR text per page
    (and 404 when no page in the requested range has transcribed text yet).
    """

    page_index: int = field(metadata=field_options(alias="pageIndex"))
    """0-based index of the page in the notebook."""

    page_id: str = field(metadata=field_options(alias="pageId"))
    """Stable unique page identifier from the `.note` file (e.g. 'P20231027120000abc')."""

    text: str | None = None
    """Extracted OCR text for the page, or `None` if unprocessed."""

    date: str | None = None
    """Inferred ISO date (`YYYY-MM-DD`) parsed from `page_id`, if present."""

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

    file_id: int = field(metadata=field_options(alias="fileId"))
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
    """Request DTO for retrieving structured notebook-level metadata."""

    file_id: int = field(metadata=field_options(alias="fileId"))
    """The unique ID of the notebook."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebNotePageMetadataRequestDTO(DataClassJSONMixin):
    """Request DTO for retrieving per-page metadata for a notebook or page range."""

    file_id: int = field(metadata=field_options(alias="fileId"))
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
class NoteRectVO(DataClassJSONMixin):
    """Bounding box rectangle in canvas pixel coordinates."""

    left: int
    top: int
    right: int
    bottom: int

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class NoteKeywordVO(DataClassJSONMixin):
    """User-authored or recognized keyword anchored to a notebook page."""

    page_number: int = field(metadata=field_options(alias="pageNumber"))
    text: str
    rect: NoteRectVO | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class NoteTitleVO(DataClassJSONMixin):
    """Heading/outline entry anchored to a notebook page."""

    page_number: int = field(metadata=field_options(alias="pageNumber"))
    level: int | None = None
    style: str | None = None
    rect: NoteRectVO | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class NoteLinkVO(DataClassJSONMixin):
    """Hyperlink entry anchored to a notebook page."""

    page_number: int = field(metadata=field_options(alias="pageNumber"))
    link_type: int = field(metadata=field_options(alias="linkType"))
    direction: int
    style: str | None = None
    target: str | None = None
    target_file_id: str | None = field(
        metadata=field_options(alias="targetFileId"), default=None
    )
    target_page_id: str | None = field(
        metadata=field_options(alias="targetPageId"), default=None
    )
    target_page_number: int | None = field(
        metadata=field_options(alias="targetPageNumber"), default=None
    )
    rect: NoteRectVO | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class NotePageMetadataVO(DataClassJSONMixin):
    """Per-page structural metadata, ink/drawable flags, and annotations."""

    page_index: int = field(metadata=field_options(alias="pageIndex"))
    page_id: str = field(metadata=field_options(alias="pageId"))
    date: str | None = None
    style: str | None = None
    style_label: str | None = field(
        metadata=field_options(alias="styleLabel"), default=None
    )
    style_hash: str | None = field(
        metadata=field_options(alias="styleHash"), default=None
    )
    orientation: str = "1000"
    recogn_status: int = field(metadata=field_options(alias="recognStatus"), default=0)
    has_ink: bool = field(metadata=field_options(alias="hasInk"), default=False)
    has_drawables: bool = field(
        metadata=field_options(alias="hasDrawables"), default=False
    )
    has_textbox: bool = field(metadata=field_options(alias="hasTextbox"), default=False)
    has_vector_graph: bool = field(
        metadata=field_options(alias="hasVectorGraph"), default=False
    )
    has_content: bool = field(metadata=field_options(alias="hasContent"), default=False)
    five_star: list[str] = field(
        metadata=field_options(alias="fiveStar"), default_factory=list
    )
    keywords: list[NoteKeywordVO] = field(default_factory=list)
    titles: list[NoteTitleVO] = field(default_factory=list)
    links: list[NoteLinkVO] = field(default_factory=list)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebNoteMetadataVO(BaseResponse):
    """Response VO for structured notebook-level metadata.

    Used by: POST /api/extended/file/note/metadata
    """

    file_id: int = field(metadata=field_options(alias="fileId"), default=0)
    native_file_id: str | None = field(
        metadata=field_options(alias="nativeFileId"), default=None
    )
    file_type: str | None = field(
        metadata=field_options(alias="fileType"), default=None
    )
    equipment: str | None = None
    signature: str | None = None
    width: int | None = None
    height: int | None = None
    total_pages: int = field(metadata=field_options(alias="totalPages"), default=0)
    recogn_language: str | None = field(
        metadata=field_options(alias="recognLanguage"), default=None
    )
    realtime_recognition: bool = field(
        metadata=field_options(alias="realtimeRecognition"), default=False
    )
    keywords: list[NoteKeywordVO] = field(default_factory=list)
    titles: list[NoteTitleVO] = field(default_factory=list)
    links: list[NoteLinkVO] = field(default_factory=list)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebNotePageMetadataVO(BaseResponse):
    """Response VO for structured per-page metadata.

    Used by: POST /api/extended/file/note/page/metadata
    """

    file_id: int = field(metadata=field_options(alias="fileId"), default=0)
    total_pages: int = field(metadata=field_options(alias="totalPages"), default=0)
    pages: list[NotePageMetadataVO] = field(default_factory=list)

    class Config(BaseConfig):
        serialize_by_alias = True
