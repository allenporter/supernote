"""Data models for the cross-notebook page timeline API (`/api/extended/timeline/*`)."""

from __future__ import annotations

from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from supernote.models.base import BaseResponse

__all__ = [
    "TimelineDayCountVO",
    "TimelineDaysRequestDTO",
    "TimelineDaysVO",
    "TimelinePageVO",
    "TimelinePagesRequestDTO",
    "TimelinePagesVO",
]


@dataclass
class TimelineDaysRequestDTO(DataClassJSONMixin):
    """Request DTO for calendar day activity counts (`POST /api/extended/timeline/days`)."""

    start_date: str | None = field(
        metadata=field_options(alias="startDate"), default=None
    )
    """Optional inclusive start date (`YYYY-MM-DD`)."""

    end_date: str | None = field(metadata=field_options(alias="endDate"), default=None)
    """Optional inclusive end date (`YYYY-MM-DD`)."""

    include_blank: bool = field(
        metadata=field_options(alias="includeBlank"), default=False
    )
    """When True, include pages without foreground drawables."""

    starred_only: bool = field(
        metadata=field_options(alias="starredOnly"), default=False
    )
    """When True, return only pages containing a five-star mark."""

    tz_offset_minutes: int = field(
        metadata=field_options(alias="tzOffsetMinutes"), default=0
    )
    """Client timezone offset in minutes east of UTC (e.g. `-480` for UTC-8)."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class TimelinePagesRequestDTO(TimelineDaysRequestDTO):
    """Request DTO for paginated timeline pages (`POST /api/extended/timeline/pages`)."""

    limit: int = 40
    """Maximum number of items to return (`1..100`, default `40`)."""

    cursor: str | None = None
    """Opaque pagination cursor returned as `nextCursor` by a prior response."""


@dataclass
class TimelinePageVO(DataClassJSONMixin):
    """Single page entry on a specific day in the cross-notebook timeline."""

    date: str
    """Calendar day (`YYYY-MM-DD`) in the requested timezone."""

    timestamp_ms: int = field(metadata=field_options(alias="timestampMs"))
    """Sort timestamp (UTC epoch ms) for this activity entry."""

    file_id: int = field(metadata=field_options(alias="fileId", serialize=str))
    """VFS file ID of the parent notebook."""

    file_name: str = field(metadata=field_options(alias="fileName"))
    """Display filename of the parent notebook."""

    page_index: int = field(metadata=field_options(alias="pageIndex"))
    """0-based index of the page within the notebook."""

    page_id: str = field(metadata=field_options(alias="pageId"))
    """Stable device `<PAGEID>` (empty string on legacy firmware)."""

    sources: list[str] = field(default_factory=list)
    """Activity provenance labels for this page on `date` (`created`, `edited`, `dated`)."""

    is_blank: bool = field(metadata=field_options(alias="isBlank"), default=False)
    has_five_star: bool = field(
        metadata=field_options(alias="hasFiveStar"), default=False
    )
    keywords: list[str] = field(default_factory=list)
    summary: str | None = None
    """Optional AI summary snippet for this page/date when the `summary` component is active."""
    image_url: str | None = field(
        metadata=field_options(alias="imageUrl"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class TimelinePagesVO(BaseResponse):
    """Paginated response VO for `POST /api/extended/timeline/pages`."""

    items: list[TimelinePageVO] = field(default_factory=list)
    next_cursor: str | None = field(
        metadata=field_options(alias="nextCursor"), default=None
    )
    has_more: bool = field(metadata=field_options(alias="hasMore"), default=False)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class TimelineDayCountVO(DataClassJSONMixin):
    """Activity summary for a single calendar day."""

    date: str
    count: int
    created_count: int = field(metadata=field_options(alias="createdCount"), default=0)
    edited_count: int = field(metadata=field_options(alias="editedCount"), default=0)
    dated_count: int = field(metadata=field_options(alias="datedCount"), default=0)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class TimelineDaysVO(BaseResponse):
    """Response VO for `POST /api/extended/timeline/days`."""

    days: list[TimelineDayCountVO] = field(default_factory=list)

    class Config(BaseConfig):
        serialize_by_alias = True
