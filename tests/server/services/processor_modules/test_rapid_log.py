"""Unit and integration tests for RapidLogModule and RapidLogEntryDO."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from supernote.models.base import TaskType
from supernote.models.schedule import ScheduleTaskLinkDTO
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    RapidLogEntryDO,
    SystemTaskDO,
)
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus, NoteDeletedEvent
from supernote.server.services.file import FileService
from supernote.server.services.processor import ProcessorService
from supernote.server.services.processor_modules.page_hashing import PageHashingModule
from supernote.server.services.processor_modules.rapid_log import (
    DEFAULT_NOTES_TASK_GROUP_TITLE,
    RapidLogModule,
)
from supernote.server.services.schedule import MAX_TITLE_LENGTH, ScheduleService
from supernote.server.services.summary import SummaryService


def _utc_ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


@pytest.fixture
def schedule_service(
    session_manager: DatabaseSessionManager,
) -> ScheduleService:
    return ScheduleService(session_manager=session_manager, event_bus=LocalEventBus())


@pytest.fixture
def rapid_log_module(
    file_service: FileService,
    schedule_service: ScheduleService,
) -> RapidLogModule:
    return RapidLogModule(
        file_service=file_service,
        schedule_service=schedule_service,
    )


async def _reset_rapid_log_checkpoint(
    session_manager: DatabaseSessionManager, file_id: int
) -> None:
    async with session_manager.session() as session:
        await session.execute(
            delete(SystemTaskDO).where(
                SystemTaskDO.file_id == file_id,
                SystemTaskDO.task_type == TaskType.RAPID_LOG_EXTRACTION.value,
            )
        )
        await session.commit()


async def test_index_rapid_log_entries_and_sync_open_tasks_with_deep_links(
    rapid_log_module: RapidLogModule,
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
                    "* o Architecture sync with team at 2pm\n"
                    "  - Room 4B\n"
                    "- Postgres vs SQLite tradeoffs noted\n"
                ),
            )
        )
        await session.commit()

    assert await rapid_log_module.run(file_id, session_manager)

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

    # Verify all 5 Rapid Log items (3 TASKs, 1 EVENT, 1 NOTE) are indexed in RapidLogEntryDO
    async with session_manager.session() as session:
        entries = {
            (r.kind, r.normalized_text): r
            for r in (
                await session.execute(
                    select(RapidLogEntryDO).where(RapidLogEntryDO.file_id == file_id)
                )
            )
            .scalars()
            .all()
        }
        assert len(entries) == 5

        open_task = entries[("TASK", "send q3 architecture proposal")]
        assert open_task.schedule_task_id == task.task_id
        assert open_task.task_state == "INCOMPLETE"
        assert open_task.is_starred is True
        assert open_task.is_cancelled is False
        assert open_task.page_date_ms == _utc_ms(2026, 10, 26)

        pre_completed = entries[("TASK", "historical completed item on first sight")]
        assert pre_completed.schedule_task_id is None
        assert pre_completed.task_state == "COMPLETED"

        pre_cancelled = entries[("TASK", "historical cancelled item on first sight")]
        assert pre_cancelled.schedule_task_id is None
        assert pre_cancelled.task_state == "CANCELLED"
        assert pre_cancelled.is_cancelled is True

        event_entry = entries[("EVENT", "architecture sync with team at 2pm")]
        assert event_entry.schedule_task_id is None
        assert event_entry.task_state is None
        assert event_entry.is_starred is True
        assert event_entry.is_cancelled is False
        assert event_entry.detail == "- Room 4B"
        assert event_entry.page_date_ms == _utc_ms(2026, 10, 26)

        note_entry = entries[("NOTE", "postgres vs sqlite tradeoffs noted")]
        assert note_entry.schedule_task_id is None
        assert note_entry.task_state is None
        assert note_entry.is_starred is False


async def test_event_and_note_updates_cancellation_and_erasure(
    rapid_log_module: RapidLogModule,
    session_manager: DatabaseSessionManager,
) -> None:
    user_id = 206
    file_id = 5006

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email="u206@example.com", password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="sk_5006",
                file_name="Events.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P20261101100000E",
                content_hash="h1",
                text_content=(
                    "o Dentist appointment at 10am\n- Bring insurance card\n"
                ),
            )
        )
        await session.commit()

    await rapid_log_module.run(file_id, session_manager)

    # Cancel the event with strikethrough and erase the note
    async with session_manager.session() as session:
        page = (
            await session.execute(
                select(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
            )
        ).scalar_one()
        page.text_content = "~~o Dentist appointment at 10am~~\n"
        await session.commit()

    await _reset_rapid_log_checkpoint(session_manager, file_id)
    await rapid_log_module.run(file_id, session_manager)

    async with session_manager.session() as session:
        rows = (
            (
                await session.execute(
                    select(RapidLogEntryDO).where(RapidLogEntryDO.file_id == file_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].kind == "EVENT"
        assert rows[0].text == "Dentist appointment at 10am"
        assert rows[0].is_cancelled is True


async def test_bullet_journal_migration_transfers_ownership(
    rapid_log_module: RapidLogModule,
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
                page_id="P20261026090000MON",
                content_hash="h1",
                text_content="# 2026-10-26\n• Call Bob\n  - Ask about contract\n",
            )
        )
        await session.commit()

    # Step 1: Monday capture
    await rapid_log_module.run(file_id, session_manager)
    tasks = await schedule_service.list_tasks(user_id)
    assert len(tasks) == 1
    original_task_id = tasks[0].task_id

    # Step 2: Monday evening -> user changes '•' to '>' on Page 1
    async with session_manager.session() as session:
        p_mon = (
            await session.execute(
                select(NotePageContentDO).where(
                    NotePageContentDO.file_id == file_id,
                    NotePageContentDO.page_id == "P20261026090000MON",
                )
            )
        ).scalar_one()
        p_mon.text_content = "# 2026-10-26\n> Call Bob\n  - Ask about contract\n"
        await session.commit()

    await _reset_rapid_log_checkpoint(session_manager, file_id)
    await rapid_log_module.run(file_id, session_manager)

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
                page_id="P20261027090000TUE",
                content_hash="h2",
                text_content="# 2026-10-27\n• Call Bob\n",
            )
        )
        await session.commit()

    await _reset_rapid_log_checkpoint(session_manager, file_id)
    await rapid_log_module.run(file_id, session_manager)

    # Single task in ScheduleService, now linked to Page 2 with Tuesday's due_time
    tasks = await schedule_service.list_tasks(user_id)
    assert len(tasks) == 1
    migrated = tasks[0]
    assert migrated.task_id == original_task_id
    assert migrated.due_time == _utc_ms(2026, 10, 27)
    assert migrated.detail == "- Ask about contract"
    assert migrated.links is not None
    link = ScheduleTaskLinkDTO.from_b64(migrated.links)
    assert link.page == 2
    assert link.page_id == "P20261027090000TUE"

    # Page 1 surrendered schedule_task_id ownership; Page 2 now owns original_task_id
    async with session_manager.session() as session:
        rows_by_page = {
            r.page_id: r
            for r in (
                await session.execute(
                    select(RapidLogEntryDO).where(RapidLogEntryDO.file_id == file_id)
                )
            )
            .scalars()
            .all()
        }
        assert rows_by_page["P20261026090000MON"].schedule_task_id is None
        assert rows_by_page["P20261026090000MON"].task_state == "MIGRATED_FORWARD"
        assert rows_by_page["P20261027090000TUE"].schedule_task_id == original_task_id
        assert rows_by_page["P20261027090000TUE"].task_state == "INCOMPLETE"

    # Step 4: Re-syncing unchanged pages skips ScheduleService via content_hash
    await _reset_rapid_log_checkpoint(session_manager, file_id)
    await rapid_log_module.run(file_id, session_manager)
    tasks = await schedule_service.list_tasks(user_id)
    assert len(tasks) == 1
    assert ScheduleTaskLinkDTO.from_b64(tasks[0].links or "").page == 2


async def test_content_hash_preserves_digital_completion_and_deletion(
    rapid_log_module: RapidLogModule,
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

    await rapid_log_module.run(file_id, session_manager)
    tasks = {t.title: t for t in await schedule_service.list_tasks(user_id)}
    assert len(tasks) == 2

    # 1. User completes 'Buy milk' digitally in the To-Do app while ink is still '• Buy milk'
    await schedule_service.update_task(
        user_id, tasks["Buy milk"].task_id, status="completed", completed_time=123456
    )

    # 2. User deletes 'Renew passport' digitally in the To-Do app while ink is still '• Renew passport'
    await schedule_service.delete_task(user_id, tasks["Renew passport"].task_id)

    # 3. User adds non-todo notes to Page 1 (and adds an indented note to 'Renew passport')
    async with session_manager.session() as session:
        page = (
            await session.execute(
                select(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
            )
        ).scalar_one()
        page.text_content = (
            "• Buy milk\n"
            "• Renew passport\n"
            "  - Bring 2 photos\n"
            "- Unrelated meeting note\n"
        )
        await session.commit()

    await _reset_rapid_log_checkpoint(session_manager, file_id)
    await rapid_log_module.run(file_id, session_manager)

    remaining = await schedule_service.list_tasks(user_id)
    assert len(remaining) == 1
    # Digital completion of 'Buy milk' was NOT overwritten back to needsAction
    assert remaining[0].title == "Buy milk"
    assert remaining[0].status == "completed"
    # 'Renew passport' was NOT respawned even after an indented note changed its content_hash


async def test_handwritten_completion_strikethrough_and_erased_cleanup(
    rapid_log_module: RapidLogModule,
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

    await rapid_log_module.run(file_id, session_manager)
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

    await _reset_rapid_log_checkpoint(session_manager, file_id)
    await rapid_log_module.run(file_id, session_manager)

    # Task B (cancelled) and Task C (erased while open) are deleted; Task A is completed
    tasks = await schedule_service.list_tasks(user_id)
    assert len(tasks) == 1
    assert tasks[0].title == "Task A"
    assert tasks[0].status == "completed"

    async with session_manager.session() as session:
        entries_by_text = {
            r.normalized_text: r
            for r in (
                await session.execute(
                    select(RapidLogEntryDO).where(RapidLogEntryDO.file_id == file_id)
                )
            )
            .scalars()
            .all()
        }
        assert entries_by_text["task a"].task_state == "COMPLETED"
        assert entries_by_text["task a"].schedule_task_id == tasks[0].task_id
        assert entries_by_text["task b"].task_state == "CANCELLED"
        assert entries_by_text["task b"].is_cancelled is True
        assert entries_by_text["task b"].schedule_task_id is None
        # Erased line has its RapidLogEntryDO row deleted outright rather than leaving tombstones
        assert "task c" not in entries_by_text


async def test_implicit_migration_and_note_deleted_cleanup(
    rapid_log_module: RapidLogModule,
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
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P20261026090000D1",
                content_hash="h1",
                text_content=(
                    "# 2026-10-26\n"
                    "• Plan offsite\n"
                    "• Already finished task\n"
                    "o Offsite kickoff meeting\n"
                ),
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=1,
                page_id="P20261027090000D2",
                content_hash="h2",
                text_content="# 2026-10-27\n• Plan offsite\nX Already finished task\n",
            )
        )
        await session.commit()

    await rapid_log_module.run(file_id, session_manager)

    tasks = {t.title: t for t in await schedule_service.list_tasks(user_id)}
    assert len(tasks) == 2
    assert ScheduleTaskLinkDTO.from_b64(tasks["Plan offsite"].links or "").page == 2
    assert tasks["Plan offsite"].status == "needsAction"
    assert tasks["Already finished task"].status == "completed"

    processor = ProcessorService(
        event_bus=event_bus,
        session_manager=session_manager,
        file_service=file_service,
        summary_service=summary_service,
    )
    processor.register_modules(
        hashing=PageHashingModule(file_service=file_service),
        rapid_log=rapid_log_module,
    )
    await processor.handle_note_deleted(
        NoteDeletedEvent(file_id=file_id, user_id=user_id)
    )
    assert processor._file_locks == {}
    assert processor._file_lock_refcounts == {}

    surviving_tasks = await schedule_service.list_tasks(user_id)
    assert len(surviving_tasks) == 1
    assert surviving_tasks[0].title == "Already finished task"
    assert surviving_tasks[0].status == "completed"

    async with session_manager.session() as session:
        remaining_entries = (
            (
                await session.execute(
                    select(RapidLogEntryDO).where(RapidLogEntryDO.file_id == file_id)
                )
            )
            .scalars()
            .all()
        )
        assert remaining_entries == []


async def test_overlong_ocr_title_truncates_safely_without_duplicate_storm(
    rapid_log_module: RapidLogModule,
    schedule_service: ScheduleService,
    session_manager: DatabaseSessionManager,
) -> None:
    user_id = 207
    file_id = 5007
    long_text = "Review distributed consensus edge cases " * 9  # 360 chars (> 255)
    long_text = long_text.strip()

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email="u207@example.com", password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="sk_5007",
                file_name="Long.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P20261028090000L",
                content_hash="h1",
                text_content=(
                    f"• Short task before long bullet\n"
                    f"• {long_text}\n"
                    f"  - Extra child context\n"
                ),
            )
        )
        await session.commit()

    assert await rapid_log_module.run(file_id, session_manager)

    tasks = await schedule_service.list_tasks(user_id)
    assert len(tasks) == 2
    long_task = next(t for t in tasks if t.title != "Short task before long bullet")
    assert len(long_task.title or "") == MAX_TITLE_LENGTH
    assert (long_task.title or "").endswith("…")
    assert long_text in (long_task.detail or "")
    assert "- Extra child context" in (long_task.detail or "")

    # Re-running must be 100% idempotent with zero duplicates
    await _reset_rapid_log_checkpoint(session_manager, file_id)
    assert await rapid_log_module.run(file_id, session_manager)
    assert len(await schedule_service.list_tasks(user_id)) == 2


async def test_page_insertion_shift_preserves_digital_metadata_edits(
    rapid_log_module: RapidLogModule,
    schedule_service: ScheduleService,
    session_manager: DatabaseSessionManager,
) -> None:
    user_id = 208
    file_id = 5008
    digital_due_ms = _utc_ms(2026, 11, 15)

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email="u208@example.com", password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="sk_5008",
                file_name="Taxes.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P_UNDATED_TAX",
                content_hash="h1",
                text_content="• File taxes\n",
            )
        )
        await session.commit()

    await rapid_log_module.run(file_id, session_manager)
    task = (await schedule_service.list_tasks(user_id))[0]

    # User digitally sets due_time, importance, and detail in the To-Do app
    await schedule_service.update_task(
        user_id,
        task.task_id,
        due_time=digital_due_ms,
        importance="high",
        detail="CPA phone: 555-0199",
    )

    # User inserts a cover page at page_index=0, shifting P_UNDATED_TAX to page_index=1
    async with session_manager.session() as session:
        existing_page = (
            await session.execute(
                select(NotePageContentDO).where(
                    NotePageContentDO.file_id == file_id,
                    NotePageContentDO.page_id == "P_UNDATED_TAX",
                )
            )
        ).scalar_one()
        existing_page.page_index = 1
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P_COVER",
                content_hash="h0",
                text_content="# 2026 Tax Prep Cover\n",
            )
        )
        await session.commit()

    await _reset_rapid_log_checkpoint(session_manager, file_id)
    await rapid_log_module.run(file_id, session_manager)

    updated_task = (await schedule_service.list_tasks(user_id))[0]
    # Deep-link advanced to page 2 while preserving all user-edited digital fields
    assert ScheduleTaskLinkDTO.from_b64(updated_task.links or "").page == 2
    assert updated_task.due_time == digital_due_ms
    assert updated_task.importance == "high"
    assert updated_task.detail == "CPA phone: 555-0199"


async def test_backwards_ownership_theft_blocked_and_scheduled_back_allowed(
    rapid_log_module: RapidLogModule,
    schedule_service: ScheduleService,
    session_manager: DatabaseSessionManager,
) -> None:
    user_id = 209
    file_id = 5009

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email="u209@example.com", password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="sk_5009",
                file_name="BuJo.note",
                directory_id=0,
            )
        )
        # Page 0 has pre-completed 'X Call Bob' and Monthly Log header;
        # Page 1 has active '• Call Bob' and scheduled-back '< Buy gift'
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P_MONTHLY",
                content_hash="h0",
                text_content="# 2026-11-01\nX Call Bob\n",
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=1,
                page_id="P_DAILY",
                content_hash="h1",
                text_content="# 2026-11-05\n• Call Bob\n< Buy gift\n",
            )
        )
        await session.commit()

    await rapid_log_module.run(file_id, session_manager)
    initial_tasks = {t.title: t for t in await schedule_service.list_tasks(user_id)}
    assert len(initial_tasks) == 2
    assert ScheduleTaskLinkDTO.from_b64(initial_tasks["Call Bob"].links or "").page == 2

    # Now Page 0 edits 'X Call Bob' -> '• Call Bob' AND adds '• Buy gift' (claiming '< Buy gift' from Page 1)
    async with session_manager.session() as session:
        p0 = (
            await session.execute(
                select(NotePageContentDO).where(
                    NotePageContentDO.file_id == file_id,
                    NotePageContentDO.page_id == "P_MONTHLY",
                )
            )
        ).scalar_one()
        p0.text_content = "# 2026-11-01\n• Call Bob\n• Buy gift\n"
        await session.commit()

    await _reset_rapid_log_checkpoint(session_manager, file_id)
    await rapid_log_module.run(file_id, session_manager)

    after_tasks = {t.title: t for t in await schedule_service.list_tasks(user_id)}
    assert len(after_tasks) == 2
    # 'Call Bob' stays anchored to Page 2 (not stolen backwards to Page 1 and not duplicated)
    assert ScheduleTaskLinkDTO.from_b64(after_tasks["Call Bob"].links or "").page == 2
    assert after_tasks["Call Bob"].due_time == _utc_ms(2026, 11, 5)
    # 'Buy gift' WAS explicitly migrated ('<') on Page 2, so Monthly Page 1 cleanly claims it!
    assert ScheduleTaskLinkDTO.from_b64(after_tasks["Buy gift"].links or "").page == 1
    assert after_tasks["Buy gift"].due_time == _utc_ms(2026, 11, 1)


async def test_header_date_bare_strikethrough_dedup_and_empty_note_recovery(
    rapid_log_module: RapidLogModule,
    schedule_service: ScheduleService,
    file_service: FileService,
    summary_service: SummaryService,
    session_manager: DatabaseSessionManager,
) -> None:
    user_id = 210
    file_id = 5010

    async with session_manager.session() as session:
        session.add(UserDO(id=user_id, email="u210@example.com", password_md5="hash"))
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key="sk_5010",
                file_name="NightBefore.note",
                directory_id=0,
            )
        )
        # Created Sunday Oct 25 (`P20261025...`), but explicit Monday `# 2026-10-26` header!
        # Also includes a crossed-out duplicate alongside a live bullet, plus bare prose strikethrough.
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P20261025223000SUN",
                content_hash="h1",
                text_content=(
                    "# 2026-10-26\n"
                    "• Ship release\n"
                    "~~• Ship release~~\n"
                    "o Team retro\n"
                    "~~Random crossed out prose sentence~~\n"
                ),
            )
        )
        await session.commit()

    await rapid_log_module.run(file_id, session_manager)

    tasks = await schedule_service.list_tasks(user_id)
    assert len(tasks) == 1
    assert tasks[0].title == "Ship release"
    # Header date (# 2026-10-26) takes precedence over Sunday page_id creation date
    assert tasks[0].due_time == _utc_ms(2026, 10, 26)

    async with session_manager.session() as session:
        entries = {
            (r.kind, r.normalized_text): r
            for r in (
                await session.execute(
                    select(RapidLogEntryDO).where(RapidLogEntryDO.file_id == file_id)
                )
            )
            .scalars()
            .all()
        }
        # Bare prose strikethrough was NOT indexed into RapidLogEntryDO
        assert len(entries) == 2
        assert ("EVENT", "team retro") in entries
        assert entries[("EVENT", "team retro")].is_cancelled is False

    # Next sync: user scribbles over 'o Team retro' so bullet 'o' is obscured (`~~Team retro~~`)
    async with session_manager.session() as session:
        p = (
            await session.execute(
                select(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
            )
        ).scalar_one()
        p.text_content = "# 2026-10-26\n• Ship release\n~~Team retro~~\n"
        await session.commit()

    await _reset_rapid_log_checkpoint(session_manager, file_id)
    await rapid_log_module.run(file_id, session_manager)

    async with session_manager.session() as session:
        ev = (
            await session.execute(
                select(RapidLogEntryDO).where(
                    RapidLogEntryDO.file_id == file_id,
                    RapidLogEntryDO.kind == "EVENT",
                )
            )
        ).scalar_one()
        assert ev.is_cancelled is True

    # Finally, all pages are deleted from the .note file: open tasks & entries are cleaned up,
    # and recover_missing_tasks does NOT loop on the 0-page note!
    async with session_manager.session() as session:
        await session.execute(
            delete(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
        )
        await session.commit()

    await _reset_rapid_log_checkpoint(session_manager, file_id)
    assert await rapid_log_module.run(file_id, session_manager)
    assert await schedule_service.list_tasks(user_id) == []

    processor = ProcessorService(
        event_bus=LocalEventBus(),
        session_manager=session_manager,
        file_service=file_service,
        summary_service=summary_service,
    )
    processor.register_modules(
        hashing=PageHashingModule(file_service=file_service),
        rapid_log=rapid_log_module,
    )
    # Mark PAGE_HASHING completed too and verify recover_missing_tasks enqueues 0 files
    async with session_manager.session() as session:
        session.add(
            SystemTaskDO(
                file_id=file_id,
                task_type=TaskType.PAGE_HASHING.value,
                key="global",
                status="COMPLETED",
            )
        )
        await session.commit()

    await processor.recover_missing_tasks(user_id=user_id)
    assert processor.queue.qsize() == 0
