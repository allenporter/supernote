"""Data Transfer Objects (DTOs), Value Objects (VOs), and OAuth token models for MCP.

Defines the request/response schemas serialized by the MCP tools in
`supernote.server.components.mcp.server` (`ListNotebooksRequestDTO`, `ListNotebooksResponseVO`,
`SearchRequestDTO`, `SearchResponseVO`, `TranscriptRequestDTO`, `TranscriptResponseVO`,
`TaskGroupVO`, `TaskVO`, `ListTasksResponseVO`, `TaskResponseVO`, `DeleteTaskResponseVO`)
as well as the user-scoped OAuth 2.1 token models (`SupernoteAuthorizationCode`,
`SupernoteAccessToken`, `SupernoteRefreshToken`) used by `supernote.server.components.mcp.auth`.
See `supernote.guides.mcp`.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    RefreshToken,
)

from supernote.models.base import BaseResponse
from supernote.models.schedule import ScheduleTaskLinkDTO


class MCPScope(StrEnum):
    """OAuth 2.1 scopes supported by the Supernote MCP server."""

    ALL = "supernote:all"
    """Full access to Supernote MCP tools (notebooks, search, transcripts, schedule tasks, and events)."""


class LoginBridgeDecision(StrEnum):
    """User consent decision submitted to POST /login-bridge."""

    APPROVE = "approve"
    DENY = "deny"


@dataclass
class LoginBridgeRequestDTO(DataClassJSONMixin):
    """Request DTO submitted by the Web UI to POST /login-bridge."""

    decision: LoginBridgeDecision = LoginBridgeDecision.APPROVE


@dataclass
class LoginBridgeResponseVO(DataClassJSONMixin):
    """Redirect response VO returned by POST /login-bridge."""

    redirect_url: str


@dataclass
class OAuthErrorResponseVO(DataClassJSONMixin):
    """RFC 6749 OAuth error response VO returned by /login-bridge."""

    error: str
    error_description: str | None = None

    class Config(BaseConfig):
        omit_none = True


class SupernoteAuthorizationCode(AuthorizationCode):
    """OAuth 2.1 authorization code associated with a Supernote user account."""

    user_id: int


class SupernoteAccessToken(AccessToken):
    """OAuth 2.1 access token associated with a Supernote user account."""

    user_id: int
    """Authenticated Supernote user ID."""

    actor: str = "user:web"
    """Canonical domain event actor identifier (`oauth:<client_id>`, `api_key:<id>`, or `user:web`)."""


class SupernoteRefreshToken(RefreshToken):
    """OAuth 2.1 refresh token associated with a Supernote user account."""

    user_id: int


@dataclass
class SearchRequestDTO(DataClassJSONMixin):
    """Request DTO for semantic notebook search.

    Used by: search_notebook_chunks (MCP)
    """

    query: str
    """The semantic search query."""

    top_n: int = 5
    """Number of results to return (default: 5)."""

    name_filter: str | None = field(
        metadata=field_options(alias="nameFilter"), default=None
    )
    """Optional substring filter for notebook filenames."""

    date_after: str | None = field(
        metadata=field_options(alias="dateAfter"), default=None
    )
    """Filter for notes created after this date (ISO 8601)."""

    date_before: str | None = field(
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

    file_id: str = field(metadata=field_options(alias="fileId"))
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
class SearchResultVO(DataClassJSONMixin):
    """VO for a single search result result.

    Used by: search_notebook_chunks (MCP)
    """

    file_id: str = field(metadata=field_options(alias="fileId"))
    file_name: str = field(metadata=field_options(alias="fileName"))
    page_index: int = field(metadata=field_options(alias="pageIndex"))
    page_id: str = field(metadata=field_options(alias="pageId"))
    score: float
    text_preview: str = field(metadata=field_options(alias="textPreview"))
    date: str | None = None

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

    transcript: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ListNotebooksRequestDTO(DataClassJSONMixin):
    """Request DTO for listing notebooks.

    Used by: list_notebooks (MCP)
    """

    limit: int = 20
    """Maximum number of notebooks to return (default: 20)."""

    name_filter: str | None = field(
        metadata=field_options(alias="nameFilter"), default=None
    )
    """Optional substring filter for notebook filenames."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class NotebookVO(DataClassJSONMixin):
    """VO for a single notebook metadata entry.

    Used by: list_notebooks (MCP)
    """

    file_id: str = field(metadata=field_options(alias="fileId"))
    file_name: str = field(metadata=field_options(alias="fileName"))
    create_time: int = field(metadata=field_options(alias="createTime"))
    update_time: int = field(metadata=field_options(alias="updateTime"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ListNotebooksResponseVO(BaseResponse):
    """Response VO for listing notebooks.

    Used by: list_notebooks (MCP)
    """

    notebooks: list[NotebookVO] = field(default_factory=list)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class TaskGroupVO(DataClassJSONMixin):
    """VO for a schedule task group returned by MCP schedule tools."""

    task_list_id: str = field(metadata=field_options(alias="taskListId"))
    """Unique task group identifier."""

    title: str
    """Task group display title."""

    create_time: int = field(metadata=field_options(alias="createTime"))
    """Creation timestamp in UTC epoch milliseconds."""

    update_time: int = field(metadata=field_options(alias="updateTime"))
    """Last modification timestamp in UTC epoch milliseconds."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class TaskVO(DataClassJSONMixin):
    """VO for a schedule task returned by MCP schedule tools."""

    task_id: str = field(metadata=field_options(alias="taskId"))
    """Unique task identifier."""

    task_list_id: str | None = field(
        metadata=field_options(alias="taskListId"), default=None
    )
    """Parent task group ID, or `None` for the default inbox."""

    title: str = ""
    """Task title."""

    detail: str | None = None
    """Optional task notes or detail text."""

    status: str = "needsAction"
    """Task status (`'needsAction'` or `'completed'`)."""

    importance: str | None = None
    """Optional importance level."""

    due_time: int | None = field(metadata=field_options(alias="dueTime"), default=None)
    """Optional due timestamp in UTC epoch milliseconds."""

    completed_time: int | None = field(
        metadata=field_options(alias="completedTime"), default=None
    )
    """Optional completion timestamp in UTC epoch milliseconds."""

    create_time: int = field(metadata=field_options(alias="createTime"), default=0)
    """Creation timestamp in UTC epoch milliseconds."""

    update_time: int = field(metadata=field_options(alias="updateTime"), default=0)
    """Last modification timestamp in UTC epoch milliseconds."""

    link: ScheduleTaskLinkDTO | None = None
    """Decoded notebook/page deep-link metadata when present."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ListTasksResponseVO(BaseResponse):
    """Response VO for listing schedule task groups and tasks."""

    groups: list[TaskGroupVO] = field(default_factory=list)
    """User's schedule task groups."""

    tasks: list[TaskVO] = field(default_factory=list)
    """Matching schedule tasks."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class TaskResponseVO(BaseResponse):
    """Response VO for single-task create or update operations."""

    task: TaskVO | None = None
    """The created or updated schedule task."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class DeleteTaskResponseVO(BaseResponse):
    """Response VO for deleting a schedule task."""

    deleted: bool = False
    """`True` when the task was deleted."""

    class Config(BaseConfig):
        serialize_by_alias = True
