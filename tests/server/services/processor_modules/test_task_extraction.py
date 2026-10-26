"""Unit and integration tests for TaskExtractionModule and NoteTaskSyncDO tombstoning."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from supernote.models.base import TaskType
from supernote.models.schedule import ScheduleTaskLinkDTO
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NoteTaskSyncDO,
    SystemTaskDO,
)
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus, NoteDeletedEvent
from supernote.server.services.file import FileService
from supernote.server.services.processor import ProcessorService
from supernote.server.services.processor_modules.task_extraction import (
    DEFAULT_NOTES_TASK_GROUP_TITLE,
    TaskExtractionModule,
)
from supernote.server.services.schedule import ScheduleService
from supernote.server.services.summary import SummaryService


def _utc_ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


@pytest.fixture
def schedule_service(
    session_manager: DatabaseSessionManager,
) -> ScheduleService:
    return ScheduleService(session_manager=session_manager, event_bus=LocalEventBus())


@pytest.fixture
def task_extraction_module(
    file_service: FileService,
    schedule_service: ScheduleService,
) -> TaskExtractionModule:
    return TaskExtractionModule(
        file_service=file_service,
        schedule_service=schedule_service,
    )


async def _reset_task_extraction_checkpoint(
    session_manager: DatabaseSessionManager, file_id: int
) -> None:
    async with session_manager.session() as session:
        await session.execute(
            delete(SystemTaskDO).where(
                SystemTaskDO.file_id == file_id,
                SystemTaskDO.task_type == TaskType.TASK_EXTRACTION.value,
            )
        )
        await session.commit()


async def test_capture_tasks_deep_links_and_ignore_pre_completed(
    task_extraction_module: TaskExtractionModule,
    schedule_service: ScheduleService,
    session_manager: DatabaseSessionManager,
) -> None:
    user_id = 201
    file_id = 5001

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email="u201@example.com", password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="sk_5001",
                file_name="Daily.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P20261026090000A",
                content_hash="h1",
                text_content=(
                    "# 2026-10-26\n"
                    "* • Send Q3 architecture proposal\n"
                    "  - Include SQLite benchmark numbers\n"
                    "  - CC Alice\n"
                    "X Historical completed item on first sight\n"
                    "~~• Historical cancelled item on first sight~~\n"
                ),
            )
        )
        await session.commit()

    assert await task_extraction_module.run(file_id, session_manager)

    groups = await schedule_service.list_groups(user_id)
    assert len(groups) == 1
    assert groups[0].title == DEFAULT_NOTES_TASK_GROUP_TITLE

    tasks = await schedule_service.list_tasks(user_id)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.title == "Send Q3 architecture proposal"
    assert task.status == "needsAction"
    assert task.importance == "high"
    assert task.detail == "- Include SQLite benchmark numbers\n- CC Alice"
    assert task.due_time == _utc_ms(2026, 10, 26)
    assert task.links is not None

    link = ScheduleTaskLinkDTO.from_b64(task.links)
    assert link.app_name == "Note"
    assert link.page == 1
    assert link.file_id == str(file_id)
    assert link.page_id == "P20261026090000A"
    assert link.task_title == "Send Q3 architecture proposal"


async def test_bullet_journal_migration_and_superseded_tombstone(
    task_extraction_module: TaskExtractionModule,
    schedule_service: ScheduleService,
    session_manager: DatabaseSessionManager,
) -> None:
    user_id = 202
    file_id = 5002

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email="u202@example.com", password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="sk_5002",
                file_name="Daily.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P_MON",
                content_hash="h1",
                text_content="# 2026-10-26\n• Call Bob\n  - Ask about contract\n",
            )
        )
        await session.commit()

    # Step 1: Monday capture
    await task_extraction_module.run(file_id, session_manager)
    tasks = await schedule_service.list_tasks(user_id)
    assert len(tasks) == 1
    original_task_id = tasks[0].task_id

    # Step 2: Monday evening -> user changes '•' to '>' on Page 1
    async with session_manager.session() as session:
        p_mon = (
            await session.execute(
                select(NotePageContentDO).where(
                    NotePageContentDO.file_id == file_id,
                    NotePageContentDO.page_id == "P_MON",
                )
            )
        ).scalar_one()
        p_mon.text_content = "# 2026-10-26\n> Call Bob\n  - Ask about contract\n"
        await session.commit()

    await _reset_task_extraction_checkpoint(session_manager, file_id)
    await task_extraction_module.run(file_id, session_manager)

    # Task remains open ('needsAction') while waiting to be rewritten on Tuesday
    tasks = await schedule_service.list_tasks(user_id)
    assert len(tasks) == 1
    assert tasks[0].task_id == original_task_id
    assert tasks[0].status == "needsAction"

    # Step 3: Tuesday -> user writes '• Call Bob' on Page 2
    async with session_manager.session() as session:
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=1,
                page_id="P_TUE",
                content_hash="h2",
                text_content="# 2026-10-27\n• Call Bob\n",
            )
        )
        await session.commit()

    await _reset_task_extraction_checkpoint(session_manager, file_id)
    await task_extraction_module.run(file_id, session_manager)

    # Still a SINGLE task in ScheduleService, now linked to Page 2 with Tuesday's due_time!
    tasks = await schedule_service.list_tasks(user_id)
    assert len(tasks) == 1
    migrated = tasks[0]
    assert migrated.task_id == original_task_id
    assert migrated.due_time == _utc_ms(2026, 10, 27)
    # Detail from Monday is preserved even though user didn't re-copy sub-bullet on Tuesday
    assert migrated.detail == "- Ask about contract"
    assert migrated.links is not None
    link = ScheduleTaskLinkDTO.from_b64(migrated.links)
    assert link.page == 2
    assert link.page_id == "P_TUE"

    # Verify Page 1's NoteTaskSyncDO row is tombstoned as SUPERSEDED and Page 2 is ACTIVE
    async with session_manager.session() as session:
        sync_rows = (
            (
                await session.execute(
                    select(NoteTaskSyncDO)
                    .where(NoteTaskSyncDO.file_id == file_id)
                    .order_by(NoteTaskSyncDO.page_index.asc())
                )
            )
            .scalars()
            .all()
        )
        assert len(sync_rows) == 2
        assert sync_rows[0].page_id == "P_MON"
        assert sync_rows[0].sync_status == "SUPERSEDED"
        assert sync_rows[1].page_id == "P_TUE"
        assert sync_rows[1].sync_status == "ACTIVE"

    # Step 4: Re-syncing again does not duplicate or revert link to Page 1
    await _reset_task_extraction_checkpoint(session_manager, file_id)
    await task_extraction_module.run(file_id, session_manager)
    tasks = await schedule_service.list_tasks(user_id)
    assert len(tasks) == 1
    assert ScheduleTaskLinkDTO.from_b64(tasks[0].links or "").page == 2


async def test_edge_triggered_digital_completion_and_deleted_remote_tombstone(
    task_extraction_module: TaskExtractionModule,
    schedule_service: ScheduleService,
    session_manager: DatabaseSessionManager,
) -> None:
    user_id = 203
    file_id = 5003

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email="u203@example.com", password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="sk_5003",
                file_name="Tasks.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P_1",
                content_hash="h1",
                text_content="• Buy milk\n• Renew passport\n",
            )
        )
        await session.commit()

    await task_extraction_module.run(file_id, session_manager)
    tasks = {t.title: t for t in await schedule_service.list_tasks(user_id)}
    assert len(tasks) == 2

    # 1. User completes 'Buy milk' digitally in the To-Do app while ink is still '• Buy milk'
    await schedule_service.update_task(
        user_id, tasks["Buy milk"].task_id, status="completed", completed_time=123456
    )

    # 2. User deletes 'Renew passport' digitally in the To-Do app while ink is still '• Renew passport'
    await schedule_service.delete_task(user_id, tasks["Renew passport"].task_id)

    # 3. Page 1 is edited and re-synced while both lines still have '•' in handwriting
    await _reset_task_extraction_checkpoint(session_manager, file_id)
    await task_extraction_module.run(file_id, session_manager)

    remaining = await schedule_service.list_tasks(user_id)
    assert len(remaining) == 1
    # Digital completion of 'Buy milk' was NOT overwritten back to needsAction!
    assert remaining[0].title == "Buy milk"
    assert remaining[0].status == "completed"

    # 'Renew passport' was tombstoned as DELETED_REMOTE and NOT zombie-respawned!
    async with session_manager.session() as session:
        passport_sync = (
            await session.execute(
                select(NoteTaskSyncDO).where(
                    NoteTaskSyncDO.file_id == file_id,
                    NoteTaskSyncDO.normalized_title == "renew passport",
                )
            )
        ).scalar_one()
        assert passport_sync.sync_status == "DELETED_REMOTE"


async def test_handwritten_completion_strikethrough_and_erased_cleanup(
    task_extraction_module: TaskExtractionModule,
    schedule_service: ScheduleService,
    session_manager: DatabaseSessionManager,
) -> None:
    user_id = 204
    file_id = 5004

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email="u204@example.com", password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="sk_5004",
                file_name="Sprint.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P_1",
                content_hash="h1",
                text_content="• Task A\n• Task B\n• Task C\n",
            )
        )
        await session.commit()

    await task_extraction_module.run(file_id, session_manager)
    assert len(await schedule_service.list_tasks(user_id)) == 3

    # Update Page 1:
    # - Task A marked completed in ink ('X Task A')
    # - Task B crossed out ('~~• Task B~~')
    # - Task C erased completely from the page
    async with session_manager.session() as session:
        page = (
            await session.execute(
                select(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
            )
        ).scalar_one()
        page.text_content = "X Task A\n~~• Task B~~\n"
        await session.commit()

    await _reset_task_extraction_checkpoint(session_manager, file_id)
    await task_extraction_module.run(file_id, session_manager)

    # Task B (cancelled) and Task C (erased while open) are deleted; Task A is completed
    tasks = await schedule_service.list_tasks(user_id)
    assert len(tasks) == 1
    assert tasks[0].title == "Task A"
    assert tasks[0].status == "completed"

    async with session_manager.session() as session:
        sync_by_title = {
            r.normalized_title: r
            for r in (
                await session.execute(
                    select(NoteTaskSyncDO).where(NoteTaskSyncDO.file_id == file_id)
                )
            )
            .scalars()
            .all()
        }
        assert sync_by_title["task a"].sync_status == "ACTIVE"
        assert sync_by_title["task a"].last_ocr_state == "COMPLETED"
        assert sync_by_title["task b"].sync_status == "CANCELLED"
        assert sync_by_title["task c"].sync_status == "ERASED"


async def test_implicit_migration_and_note_deleted_cleanup(
    task_extraction_module: TaskExtractionModule,
    schedule_service: ScheduleService,
    file_service: FileService,
    summary_service: SummaryService,
    session_manager: DatabaseSessionManager,
) -> None:
    user_id = 205
    file_id = 5005
    event_bus = LocalEventBus()

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email="u205@example.com", password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="sk_5005",
                file_name="Journal.note",
                directory_id=0,
            )
        )
        # Implicit migration: User writes '• Plan offsite' on Page 1 and Page 2 without '>'
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P_DAY1",
                content_hash="h1",
                text_content="# 2026-10-26\n• Plan offsite\n• Already finished task\n",
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=1,
                page_id="P_DAY2",
                content_hash="h2",
                text_content="# 2026-10-27\n• Plan offsite\nX Already finished task\n",
            )
        )
        await session.commit()

    await task_extraction_module.run(file_id, session_manager)

    tasks = {t.title: t for t in await schedule_service.list_tasks(user_id)}
    assert len(tasks) == 2
    # 'Plan offsite' was deduplicated across pages and linked to Page 2
    assert ScheduleTaskLinkDTO.from_b64(tasks["Plan offsite"].links or "").page == 2
    assert tasks["Plan offsite"].status == "needsAction"
    # 'Already finished task' was captured on Page 1 and completed on Page 2
    assert tasks["Already finished task"].status == "completed"

    # Now delete the note via ProcessorService.handle_note_deleted:
    # Open task ('Plan offsite') should be removed; completed task should remain
    processor = ProcessorService(
        event_bus=event_bus,
        session_manager=session_manager,
        file_service=file_service,
        summary_service=summary_service,
    )
    await processor.handle_note_deleted(
        NoteDeletedEvent(file_id=file_id, user_id=user_id)
    )

    surviving_tasks = await schedule_service.list_tasks(user_id)
    assert len(surviving_tasks) == 1
    assert surviving_tasks[0].title == "Already finished task"
    assert surviving_tasks[0].status == "completed"
