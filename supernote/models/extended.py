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
