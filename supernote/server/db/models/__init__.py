"""SQLAlchemy 2.0 ORM data objects (`*DO`) representing the SQLite database schema.

| Module | ORM Models | Primary Service Consumer |
| :--- | :--- | :--- |
| `supernote.server.db.models.user` | `UserDO` (`users`) | `supernote.server.services.user.UserService` |
| `supernote.server.db.models.device` | `DeviceDO` (`devices`) | `supernote.server.services.user.UserService` |
| `supernote.server.db.models.login_record` | `LoginRecordDO` (`login_records`) | `supernote.server.services.user.UserService` |
| `supernote.server.db.models.file` | `UserFileDO` (`f_user_file`), `RecycleFileDO` (`f_recycle_file`) | `supernote.server.services.vfs.VirtualFileSystem` |
| `supernote.server.db.models.note_processing` | `NotePageContentDO` (`f_note_page_content`), `SystemTaskDO` (`f_system_task`) | `supernote.server.services.processor.ProcessorService` |
| `supernote.server.db.models.summary` | `SummaryDO` (`f_summary`), `SummaryTagDO` (`f_summary_tag`) | `supernote.server.services.summary.SummaryService` |
| `supernote.server.db.models.schedule` | `ScheduleTaskGroupDO` (`t_schedule_task_group`), `ScheduleTaskDO` (`t_schedule_task`) | `supernote.server.services.schedule.ScheduleService` |
| `supernote.server.db.models.kv` | `KeyValueDO` (`key_values`) | `supernote.server.services.coordination.SqliteCoordinationService` |

See `supernote.guides.schema_migration_guide` for Alembic migration conventions.
"""

from . import (
    device,
    file,
    kv,
    login_record,
    note_processing,
    schedule,
    summary,
    user,
)

__all__ = [
    "device",
    "file",
    "kv",
    "login_record",
    "note_processing",
    "schedule",
    "summary",
    "user",
]
