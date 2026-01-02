"""Schedule related API data models mirroring OpenAPI Spec.

The following endpoints are supported:
- /api/file/schedule/group
- /api/file/schedule/group/all
- /api/file/schedule/group/clear
- /api/file/schedule/group/{taskListId}
- /api/file/schedule/task
- /api/file/schedule/task/all
- /api/file/schedule/task/list
- /api/file/schedule/task/{taskId}
- /api/file/schedule/sort
- /api/file/schedule/sort/{taskListId}
"""

from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseResponse, BooleanEnum


@dataclass
class ScheduleTaskGroupItem(DataClassJSONMixin):
    """Schedule task group item."""

    task_list_id: str | None = field(
        metadata=field_options(alias="taskListId"), default=None
    )
    user_id: int | None = field(metadata=field_options(alias="userId"), default=None)
    title: str | None = None
    last_modified: int | None = field(
        metadata=field_options(alias="lastModified"), default=None
    )
    """Timestamp in milliseconds"""

    is_deleted: BooleanEnum | None = field(
        metadata=field_options(alias="isDeleted"), default=None
    )
    create_time: int | None = field(
        metadata=field_options(alias="createTime"), default=None
    )
    """Timestamp in milliseconds"""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ScheduleRecurTaskItem(DataClassJSONMixin):
    """Schedule recurrence task item."""

    task_id: str | None = field(metadata=field_options(alias="taskId"), default=None)
    recurrence_id: str | None = field(
        metadata=field_options(alias="recurrenceId"), default=None
    )
    task_list_id: str | None = field(
        metadata=field_options(alias="taskListId"), default=None
    )
    user_id: int | None = field(metadata=field_options(alias="userId"), default=None)
    last_modified: int | None = field(
        metadata=field_options(alias="lastModified"), default=None
    )
    """Timestamp in milliseconds"""

    due_time: int | None = field(metadata=field_options(alias="dueTime"), default=None)
    """Timestamp in milliseconds"""

    completed_time: int | None = field(
        metadata=field_options(alias="completedTime"), default=None
    )
    """Timestamp in milliseconds"""

    status: str | None = None
    """Task status string either 'needsAction' or 'completed'"""

    is_deleted: BooleanEnum | None = field(
        metadata=field_options(alias="isDeleted"), default=None
    )
    sort: int | None = None
    """Sort order index"""

    sort_completed: int | None = field(
        metadata=field_options(alias="sortCompleted"), default=None
    )
    planer_sort: int | None = field(
        metadata=field_options(alias="planerSort"), default=None
    )
    all_sort: int | None = field(metadata=field_options(alias="allSort"), default=None)
    all_sort_completed: int | None = field(
        metadata=field_options(alias="allSortCompleted"), default=None
    )
    sort_time: int | None = field(
        metadata=field_options(alias="sortTime"), default=None
    )
    planer_sort_time: int | None = field(
        metadata=field_options(alias="planerSortTime"), default=None
    )
    all_sort_time: int | None = field(
        metadata=field_options(alias="allSortTime"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ScheduleTaskInfo(DataClassJSONMixin):
    """Schedule task info details."""

    task_id: str | None = field(metadata=field_options(alias="taskId"), default=None)
    task_list_id: str | None = field(
        metadata=field_options(alias="taskListId"), default=None
    )
    title: str | None = None
    detail: str | None = None
    last_modified: int | None = field(
        metadata=field_options(alias="lastModified"), default=None
    )
    """Timestamp in milliseconds"""

    recurrence: str | None = None
    is_reminder_on: BooleanEnum | None = field(
        metadata=field_options(alias="isReminderOn"), default=None
    )
    """Whether the reminder is enabled. 'Y' for yes, 'N' for no."""

    status: str | None = None
    """Task status string"""

    importance: str | None = None
    """Task importance level"""

    due_time: int | None = field(metadata=field_options(alias="dueTime"), default=None)
    """Timestamp in milliseconds"""

    completed_time: int | None = field(
        metadata=field_options(alias="completedTime"), default=None
    )
    """Timestamp in milliseconds"""

    links: str | None = None
    """Base64 encoded json description of a link to a document with fields 'appName', 'fileId', 'path', "page', 'pageId'"""

    is_deleted: BooleanEnum | None = field(
        metadata=field_options(alias="isDeleted"), default=None
    )
    sort: int | None = None
    """Sort order index"""
    sort_completed: int | None = field(
        metadata=field_options(alias="sortCompleted"), default=None
    )
    planer_sort: int | None = field(
        metadata=field_options(alias="planerSort"), default=None
    )
    all_sort: int | None = field(metadata=field_options(alias="allSort"), default=None)
    all_sort_completed: int | None = field(
        metadata=field_options(alias="allSortCompleted"), default=None
    )
    sort_time: int | None = field(
        metadata=field_options(alias="sortTime"), default=None
    )
    planer_sort_time: int | None = field(
        metadata=field_options(alias="planerSortTime"), default=None
    )
    all_sort_time: int | None = field(
        metadata=field_options(alias="allSortTime"), default=None
    )
    schedule_recur_task: list[ScheduleRecurTaskItem] = field(
        metadata=field_options(alias="scheduleRecurTask"), default_factory=list
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class AddScheduleTaskGroupDTO(DataClassJSONMixin):
    """Request to add a schedule task group.

    Used by:
        /api/file/schedule/group (POST)
    """

    title: str
    task_list_id: str | None = field(
        metadata=field_options(alias="taskListId"), default=None
    )
    last_modified: int | None = field(
        metadata=field_options(alias="lastModified"), default=None
    )
    """Timestamp in milliseconds"""

    create_time: int | None = field(
        metadata=field_options(alias="createTime"), default=None
    )
    """Timestamp in milliseconds"""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UpdateScheduleTaskGroupDTO(DataClassJSONMixin):
    """Request to update a schedule task group.

    Used by:
        /api/file/schedule/group (PUT)
    """

    task_list_id: str = field(metadata=field_options(alias="taskListId"))
    title: str
    last_modified: int | None = field(
        metadata=field_options(alias="lastModified"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ClearScheduleTaskGroupDTO(DataClassJSONMixin):
    """Request to clear a schedule task group.

    Used by:
        /api/file/schedule/group/clear (POST)
    """

    task_list_id: str = field(metadata=field_options(alias="taskListId"))
    last_modified: int = field(metadata=field_options(alias="lastModified"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ScheduleTaskGroupDTO(DataClassJSONMixin):
    """Request to query schedule task groups.

    Used by:
        /api/file/schedule/group/all (POST)
    """

    max_results: str | None = field(
        metadata=field_options(alias="maxResults"), default=None
    )
    page_token: str | None = field(
        metadata=field_options(alias="pageToken"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class AddScheduleTaskDTO(DataClassJSONMixin):
    """Request to add a schedule task.

    Used by:
        /api/file/schedule/task (POST)
    """

    title: str
    task_list_id: str | None = field(
        metadata=field_options(alias="taskListId"), default=None
    )
    task_id: str | None = field(metadata=field_options(alias="taskId"), default=None)
    recurrence_id: str | None = field(
        metadata=field_options(alias="recurrenceId"), default=None
    )
    detail: str | None = None
    last_modified: int | None = field(
        metadata=field_options(alias="lastModified"), default=None
    )
    """Timestamp in milliseconds"""

    recurrence: str | None = None
    is_reminder_on: BooleanEnum | None = field(
        metadata=field_options(alias="isReminderOn"), default=None
    )
    """Whether the reminder is enabled. 'Y' for yes, 'N' for no."""

    status: str | None = None
    """Task status string"""

    importance: str | None = None
    """Task importance level"""

    due_time: int | None = field(metadata=field_options(alias="dueTime"), default=None)
    """Timestamp in milliseconds"""

    completed_time: int | None = field(
        metadata=field_options(alias="completedTime"), default=None
    )
    """Timestamp in milliseconds"""

    links: str | None = None
    is_deleted: BooleanEnum | None = field(
        metadata=field_options(alias="isDeleted"), default=None
    )
    sort: int | None = None
    """Sort order index"""
    sort_completed: int | None = field(
        metadata=field_options(alias="sortCompleted"), default=None
    )
    planer_sort: int | None = field(
        metadata=field_options(alias="planerSort"), default=None
    )
    all_sort: int | None = field(metadata=field_options(alias="allSort"), default=None)
    all_sort_completed: int | None = field(
        metadata=field_options(alias="allSortCompleted"), default=None
    )
    sort_time: int | None = field(
        metadata=field_options(alias="sortTime"), default=None
    )
    planer_sort_time: int | None = field(
        metadata=field_options(alias="planerSortTime"), default=None
    )
    all_sort_time: int | None = field(
        metadata=field_options(alias="allSortTime"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UpdateScheduleTaskDTO(DataClassJSONMixin):
    """Request to update a schedule task.

    Used by:
        /api/file/schedule/task (PUT)
    """

    task_id: str = field(metadata=field_options(alias="taskId"))
    title: str
    last_modified: int = field(metadata=field_options(alias="lastModified"))
    """Timestamp in milliseconds"""

    task_list_id: str | None = field(
        metadata=field_options(alias="taskListId"), default=None
    )
    recurrence_id: str | None = field(
        metadata=field_options(alias="recurrenceId"), default=None
    )
    detail: str | None = None
    recurrence: str | None = None
    is_reminder_on: BooleanEnum | None = field(
        metadata=field_options(alias="isReminderOn"), default=None
    )
    """Whether the reminder is enabled. 'Y' for yes, 'N' for no."""

    status: str | None = None
    """Task status string"""

    importance: str | None = None
    """Task importance level"""

    due_time: int | None = field(metadata=field_options(alias="dueTime"), default=None)
    """Timestamp in milliseconds"""

    completed_time: int | None = field(
        metadata=field_options(alias="completedTime"), default=None
    )
    """Timestamp in milliseconds"""

    links: str | None = None
    is_deleted: BooleanEnum | None = field(
        metadata=field_options(alias="isDeleted"), default=None
    )
    sort: int | None = None
    """Sort order index"""
    sort_completed: int | None = field(
        metadata=field_options(alias="sortCompleted"), default=None
    )
    planer_sort: int | None = field(
        metadata=field_options(alias="planerSort"), default=None
    )
    all_sort: int | None = field(metadata=field_options(alias="allSort"), default=None)
    all_sort_completed: int | None = field(
        metadata=field_options(alias="allSortCompleted"), default=None
    )
    sort_time: int | None = field(
        metadata=field_options(alias="sortTime"), default=None
    )
    planer_sort_time: int | None = field(
        metadata=field_options(alias="planerSortTime"), default=None
    )
    all_sort_time: int | None = field(
        metadata=field_options(alias="allSortTime"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UpdateScheduleTaskListDTO(DataClassJSONMixin):
    """Request to update list of schedule tasks.

    Used by:
        /api/file/schedule/task/list (PUT)
    """

    task_list_id: str | None = field(
        metadata=field_options(alias="taskListId"), default=None
    )
    update_schedule_task_list: list[UpdateScheduleTaskDTO] = field(
        metadata=field_options(alias="updateScheduleTaskList"), default_factory=list
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ScheduleTaskDTO(DataClassJSONMixin):
    """Request for keys/tokens for schedule sync.

    Used by:
        /api/file/schedule/task/all (POST)
    """

    max_results: str | None = field(
        metadata=field_options(alias="maxResults"), default=None
    )
    next_page_tokens: str | None = field(
        metadata=field_options(alias="nextPageTokens"), default=None
    )
    next_sync_token: int | None = field(
        metadata=field_options(alias="nextSyncToken"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ScheduleSortDTO(DataClassJSONMixin):
    """Request for schedule sort.

    Used by:
        /api/file/schedule/sort (POST)
        /api/file/schedule/sort (PUT)
    """

    task_list_id: str | None = field(
        metadata=field_options(alias="taskListId"), default=None
    )
    title: str | None = None
    last_modify: int | None = field(
        metadata=field_options(alias="lastModify"), default=None
    )
    """Timestamp in milliseconds"""
    content: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class GetScheduleSortDTO(DataClassJSONMixin):
    """Request/Response query for sort.

    Used by:
        /api/file/query/schedule/sort (POST)
    """

    next_index_number: int | None = field(
        metadata=field_options(alias="nextIndexNumber"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class AddScheduleTaskGroupVO(BaseResponse):
    """Response for adding schedule task group.

    Used by:
        /api/file/schedule/group (POST)
    """

    task_list_id: str | None = field(
        metadata=field_options(alias="taskListId"), default=None
    )


@dataclass(kw_only=True)
class GetScheduleTaskGroupVO(BaseResponse):
    """Response for getting specific task group.

    Used by:
        /api/file/schedule/group/{taskListId} (GET)
    """

    task_list_id: str | None = field(
        metadata=field_options(alias="taskListId"), default=None
    )
    user_id: int | None = field(metadata=field_options(alias="userId"), default=None)
    title: str | None = None
    last_modified: int | None = field(
        metadata=field_options(alias="lastModified"), default=None
    )
    """Timestamp in milliseconds"""

    is_deleted: BooleanEnum | None = field(
        metadata=field_options(alias="isDeleted"), default=None
    )
    create_time: int | None = field(
        metadata=field_options(alias="createTime"), default=None
    )
    """Timestamp in milliseconds"""


@dataclass(kw_only=True)
class ScheduleTaskGroupVO(BaseResponse):
    """Response list of schedule task groups.

    Used by:
        /api/file/schedule/group/all (POST)
    """

    page_token: str | None = field(
        metadata=field_options(alias="pageToken"), default=None
    )
    schedule_task_group: list[ScheduleTaskGroupItem] = field(
        metadata=field_options(alias="scheduleTaskGroup"), default_factory=list
    )


@dataclass(kw_only=True)
class AddScheduleTaskVO(BaseResponse):
    """Response adding schedule task.

    Used by:
        /api/file/schedule/task (POST)
    """

    task_id: str | None = field(metadata=field_options(alias="taskId"), default=None)


@dataclass(kw_only=True)
class UpdateScheduleTaskVO(BaseResponse):
    """Response updating schedule task.

    Used by:
        /api/file/schedule/task (PUT)
    """

    task_id: str | None = field(metadata=field_options(alias="taskId"), default=None)


@dataclass(kw_only=True)
class ScheduleTaskVO(BaseResponse):
    """Response for single task details.

    Used by:
        /api/file/schedule/task/{taskId} (GET)
    """

    task_id: int | None = field(metadata=field_options(alias="taskId"), default=None)
    task_list_id: int | None = field(
        metadata=field_options(alias="taskListId"), default=None
    )
    title: str | None = None
    detail: str | None = None
    last_modified: int | None = field(
        metadata=field_options(alias="lastModified"), default=None
    )
    """Timestamp in milliseconds"""

    recurrence: str | None = None
    is_reminder_on: BooleanEnum | None = field(
        metadata=field_options(alias="isReminderOn"), default=None
    )
    """Whether the reminder is enabled. 'Y' for yes, 'N' for no."""

    status: str | None = None
    """Task status string"""

    importance: str | None = None
    """Task importance level"""

    due_time: int | None = field(metadata=field_options(alias="dueTime"), default=None)
    """Timestamp in milliseconds"""

    completed_time: int | None = field(
        metadata=field_options(alias="completedTime"), default=None
    )
    """Timestamp in milliseconds"""

    links: str | None = None
    is_deleted: BooleanEnum | None = field(
        metadata=field_options(alias="isDeleted"), default=None
    )
    sort: int | None = None
    """Sort order index"""
    sort_completed: int | None = field(
        metadata=field_options(alias="sortCompleted"), default=None
    )
    planer_sort: int | None = field(
        metadata=field_options(alias="planerSort"), default=None
    )
    all_sort: int | None = field(metadata=field_options(alias="allSort"), default=None)
    all_sort_completed: int | None = field(
        metadata=field_options(alias="allSortCompleted"), default=None
    )
    sort_time: int | None = field(
        metadata=field_options(alias="sortTime"), default=None
    )
    planer_sort_time: int | None = field(
        metadata=field_options(alias="planerSortTime"), default=None
    )
    all_sort_time: int | None = field(
        metadata=field_options(alias="allSortTime"), default=None
    )
    schedule_recur_task: list[ScheduleRecurTaskItem] = field(
        metadata=field_options(alias="scheduleRecurTask"), default_factory=list
    )


@dataclass(kw_only=True)
class ScheduleTaskAllVO(BaseResponse):
    """Response for all tasks.

    Used by:
        /api/file/schedule/task/all (POST)
    """

    next_page_token: str | None = field(
        metadata=field_options(alias="nextPageToken"), default=None
    )
    next_sync_token: int | None = field(
        metadata=field_options(alias="nextSyncToken"), default=None
    )
    schedule_task: list[ScheduleTaskInfo] = field(
        metadata=field_options(alias="scheduleTask"), default_factory=list
    )


@dataclass(kw_only=True)
class GetScheduleSortVO(BaseResponse):
    """Response for sort info.

    Used by:
        /api/file/query/schedule/sort (POST)
    """

    task_list_id: str | None = field(
        metadata=field_options(alias="taskListId"), default=None
    )
    title: str | None = None
    last_modify: int | None = field(
        metadata=field_options(alias="lastModify"), default=None
    )
    content: str | None = None
    next_index_number: int | None = field(
        metadata=field_options(alias="nextIndexNumber"), default=None
    )
