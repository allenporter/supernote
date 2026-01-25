from dataclasses import dataclass, field
from typing import Optional

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    RefreshToken,
)

from supernote.models.base import BaseResponse


class SupernoteAuthorizationCode(AuthorizationCode):
    user_id: str


class SupernoteAccessToken(AccessToken):
    user_id: str


class SupernoteRefreshToken(RefreshToken):
    user_id: str


@dataclass
class SearchRequestDTO(DataClassJSONMixin):
    """Request DTO for semantic notebook search.

    Used by: search_notebook_chunks (MCP)
    """

    query: str
    """The semantic search query."""

    top_n: int = 5
    """Number of results to return (default: 5)."""

    name_filter: Optional[str] = field(
        metadata=field_options(alias="nameFilter"), default=None
    )
    """Optional substring filter for notebook filenames."""

    date_after: Optional[str] = field(
        metadata=field_options(alias="dateAfter"), default=None
    )
    """Filter for notes created after this date (ISO 8601)."""

    date_before: Optional[str] = field(
        metadata=field_options(alias="dateBefore"), default=None
    )
    """Filter for notes created before this date (ISO 8601)."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class TranscriptRequestDTO(DataClassJSONMixin):
    """Request DTO for retrieving a notebook transcript.

    Used by: get_notebook_transcript (MCP)
    """

    file_id: int = field(metadata=field_options(alias="fileId"))
    """The unique ID of the notebook."""

    start_index: Optional[int] = field(
        metadata=field_options(alias="startIndex"), default=None
    )
    """Optional 0-based start page index (inclusive)."""

    end_index: Optional[int] = field(
        metadata=field_options(alias="endIndex"), default=None
    )
    """Optional 0-based end page index (inclusive)."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SearchResultVO(DataClassJSONMixin):
    """VO for a single search result result.

    Used by: search_notebook_chunks (MCP)
    """

    file_id: int = field(metadata=field_options(alias="fileId"))
    file_name: str = field(metadata=field_options(alias="fileName"))
    page_index: int = field(metadata=field_options(alias="pageIndex"))
    page_id: str = field(metadata=field_options(alias="pageId"))
    score: float
    text_preview: str = field(metadata=field_options(alias="textPreview"))
    date: Optional[str] = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SearchResponseVO(BaseResponse):
    """Response VO for semantic search.

    Used by: search_notebook_chunks (MCP)
    """

    results: list[SearchResultVO] = field(default_factory=list)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class TranscriptResponseVO(BaseResponse):
    """Response VO for transcript retrieval.

    Used by: get_notebook_transcript (MCP)
    """

    transcript: Optional[str] = None

    class Config(BaseConfig):
        serialize_by_alias = True
