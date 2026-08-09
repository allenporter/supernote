# Schedule & Task API Specification and Behavioral Guide

This document defines the architecture, endpoint specifications, data models, and behavioral requirements for the **Schedule & Task Ecosystem** in the Supernote Private Cloud.

---

## 1. Overview & Core Concepts

The Schedule ecosystem manages user tasks, task lists (groups), recurrence rules, and sort orders for both physical Supernote hardware tablets (Nomad, A5X, A6X) and client applications (Web UI, Python SDK).

### Primary Entities

1. **Task Groups (`ScheduleTaskGroupDO` / `t_schedule_task_group`)**
   * Logical containers/lists for tasks (e.g., "Inbox", "Work", "Personal").
   * Primary key: `taskListId` (String UUID / Unique Hash).

2. **Tasks (`ScheduleTaskDO` / `t_schedule_task`)**
   * Individual action items with summary (`title`), details (`detail`), RFC 5545 status (`needsAction`, `completed`), due dates (`dueTime`), completion timestamps (`completedTime`), and optional page links (`links`).
   * Primary key: `taskId` (String UUID / Unique Hash).

3. **Recurrence Exception Instances (`ScheduleRecurTaskDO` / `t_schedule_recur_task`)**
   * Specific date/instance overrides for recurring task series.
   * Linked via `recurrenceId` -> `parent.taskId`.

4. **Task Sort Configurations (`ScheduleSortDO` / `t_schedule_sort`)**
   * Stores user-defined ordering indexes (`sort`, `sortCompleted`, `planerSort`, `allSort`).

---

## 2. Official Device & Server API Endpoints

All schedule endpoints are unified under the `/api/file/schedule/` namespace (verified against original Java controller `F_ScheduleController`):

### Task Group Management (`/api/file/schedule/group*`)
* `POST /api/file/schedule/group` — Create Task Group ([AddScheduleTaskGroupDTO](../supernote/models/schedule.py#L180-L203) → [AddScheduleTaskGroupVO](../supernote/models/schedule.py#L479-L490))
* `PUT /api/file/schedule/group` — Update Task Group ([UpdateScheduleTaskGroupDTO](../supernote/models/schedule.py#L205-L221))
* `DELETE /api/file/schedule/group/{taskListId}` — Delete Task Group
* `POST /api/file/schedule/group/clear` — Clear Task Group (soft-deletes all tasks in list)
* `GET /api/file/schedule/group/{taskListId}` — Get Task Group
* `POST /api/file/schedule/group/all` — List All Task Groups ([ScheduleTaskGroupDTO](../supernote/models/schedule.py#L238-L254) → [ScheduleTaskGroupVO](../supernote/models/schedule.py#L520-L532))

### Task Operations (`/api/file/schedule/task*`)
* `POST /api/file/schedule/task` — Create/Upsert Single Task ([AddScheduleTaskDTO](../supernote/models/schedule.py#L258-L327) → [AddScheduleTaskVO](../supernote/models/schedule.py#L535-L545))
* `PUT /api/file/schedule/task` — Update Single Task ([UpdateScheduleTaskDTO](../supernote/models/schedule.py#L330-L396))
* `PUT /api/file/schedule/task/list` — **Batch Update Tasks** ([UpdateScheduleTaskListDTO](../supernote/models/schedule.py#L400-L416))
* `DELETE /api/file/schedule/task/{taskId}` — Delete Task
* `GET /api/file/schedule/task/{taskId}` — Get Task Details ([ScheduleTaskVO](../supernote/models/schedule.py#L558-L624))
* `POST /api/file/schedule/task/all` — List All Tasks ([ScheduleTaskDTO](../supernote/models/schedule.py#L419-L438) → [ScheduleTaskAllVO](../supernote/models/schedule.py#L627-L642))

### Sort Configurations (`/api/file/schedule/sort*`)
* `POST /api/file/schedule/sort` — Add Sort Config ([ScheduleSortDTO](../supernote/models/schedule.py#L441-L461))
* `PUT /api/file/schedule/sort` — Update Sort Config
* `DELETE /api/file/schedule/sort/{taskListId}` — Delete Sort Config
* `POST /api/file/query/schedule/sort` — Query Sort Config ([GetScheduleSortDTO](../supernote/models/schedule.py#L464-L477) → [GetScheduleSortVO](../supernote/models/schedule.py#L645-L663))

### iCalendar Feed Subscriptions (`/api/schedule/feed.ics`)
* `GET /api/schedule/feed.ics` — Export user tasks in RFC 5545 `VTODO` iCalendar format (`text/calendar`) for calendar app subscriptions (Apple Reminders, Google Calendar, Outlook, Todoist). Accepts authentication via `x-access-token` header or `?token=` query parameter, with optional task list filtering via `?taskListId=`.

---

## 3. Mandatory Behavioral Requirements & Semantics

Implementing compliant Schedule service handlers requires enforcing the following behavioral contracts:

### A. Task & Group ID Generation
* **Client-Supplied IDs**: Physical tablets and clients supply their own string UUIDs for `taskId` and `taskListId`.
* **Server Fallback Requirement**: If `taskId` or `taskListId` is omitted/empty during creation:
  1. The server MUST auto-generate a unique string key (e.g., hash of `title + timestamp`).
  2. If the generated ID collides with an existing record, the server MUST handle collisions (e.g., appending incrementing suffixes) until a unique ID is assigned.

### B. All-or-Nothing Atomic Batch Guarantee (`PUT /api/file/schedule/task/list`)
* `updateScheduleTaskList` accepts a list of task updates.
* **Transactional Rule**: The batch operation **MUST be atomic (all-or-nothing)**. If *any single task ID* in the batch list does not exist in the database, the server MUST roll back the entire transaction and return error `E0329` ("Task does not exist"). Partial batch updates are prohibited.

### C. Cascade Soft-Deletes
* **Group Deletion**: Deleting a task group (`DELETE /api/file/schedule/group/{taskListId}`) MUST soft-delete (`is_deleted = 'Y'`) the group record AND automatically soft-delete all child tasks sharing that `taskListId`.
* **Group Clearing**: Clearing a group (`POST /api/file/schedule/group/clear`) MUST update the group's `lastModified` timestamp and soft-delete all tasks under that `taskListId` while leaving the group active.
* **Parent-Recurrence Soft-Delete**: Soft-deleting a parent task MUST soft-delete all linked recurrence instance overrides in `t_schedule_recur_task` (`recurrence_id = parent_task_id`).

### D. Foreign Key Validation & Default Values
* **Group Existence**: When creating or updating a task with a non-empty `taskListId`, the server MUST verify that the target task group exists. If missing, return error `E0328` ("Task list group does not exist").
* **Default Values**:
  * `isReminderOn` defaults to `"N"` if omitted.
  * `dueTime` defaults to `0` (Epoch MS) if omitted.
  * `isDeleted` defaults to `"N"` if omitted.
  * `lastModified` defaults to `0` if omitted.

### E. Real-Time Socket.IO Event Broadcasting
Every mutating API call (`create`, `update`, `delete`, `clear` on groups, tasks, or sorts) MUST emit a Socket.IO event (`scheduleTaskMessage`) to notify active user hardware sessions to trigger auto-sync.

---

## 4. Client SDK Abstraction Strategy (`ScheduleClient`)

The Python SDK ([supernote/client/schedule.py](../supernote/client/schedule.py)) provides a high-level, Pythonic interface. 

While non-spec `/api/schedule/*` server routes are removed, **the Python SDK method signatures remain clean abstractions**:

| Python SDK Method | Internal Endpoint Target | Transport / Protocol |
| :--- | :--- | :--- |
| `create_group(title)` | `POST /api/file/schedule/group` | Add group JSON payload |
| `list_groups()` | `POST /api/file/schedule/group/all` | Paginated POST query |
| `delete_group(group_id)` | `DELETE /api/file/schedule/group/{id}` | Path parameter DELETE |
| `create_task(...)` | `POST /api/file/schedule/task` | Single task DTO |
| `list_tasks(group_id)` | `POST /api/file/schedule/task/all` | Paginated POST query |
| `update_task(...)` | `PUT /api/file/schedule/task/list` | Single-item array batch PUT |
| `delete_task(task_id)` | `DELETE /api/file/schedule/task/{id}` | Path parameter DELETE |
