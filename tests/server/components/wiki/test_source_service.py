"""Tests for `supernote.server.components.wiki.source_service` (`WikiSourceService`)."""

from __future__ import annotations

from supernote.models.events import DomainEventType
from supernote.models.wiki import WikiSourceRefDTO, WikiSourceType
from supernote.server.components.wiki.source_service import WikiSourceService
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.schedule import ScheduleTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import DomainEventRecorded


async def test_load_linked_context_enforces_tenant_and_active_file_isolation(
    session_manager: DatabaseSessionManager,
) -> None:
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=101,
                    user_id=1,
                    file_name="Active.note",
                    is_folder="N",
                    is_active="Y",
                ),
                UserFileDO(
                    id=102,
                    user_id=1,
                    file_name="Deleted.note",
                    is_folder="N",
                    is_active="N",
                ),
                UserFileDO(
                    id=103,
                    user_id=2,
                    file_name="OtherUser.note",
                    is_folder="N",
                    is_active="Y",
                ),
                NotePageContentDO(
                    file_id=101,
                    page_index=0,
                    page_id="P1",
                    text_content="User 1 active note",
                ),
                NotePageContentDO(
                    file_id=102,
                    page_index=0,
                    page_id="P2",
                    text_content="User 1 deleted note",
                ),
                NotePageContentDO(
                    file_id=103,
                    page_index=0,
                    page_id="P3",
                    text_content="User 2 private note",
                ),
                ScheduleTaskDO(
                    user_id=1,
                    task_id="t1",
                    title="Ship Q3",
                    status="needsAction",
                    update_time=1000,
                ),
            ]
        )
        await session.commit()

    svc = WikiSourceService(session_manager)
    events = [
        DomainEventRecorded(
            seq=1,
            user_id=1,
            event_type=DomainEventType.SCHEDULE_TASK_CREATED.value,
            entity_type="schedule_task",
            entity_id="t1",
            related_file_id=101,
            payload={},
            actor="user:web",
            timestamp_ms=1000,
        ),
        DomainEventRecorded(
            seq=2,
            user_id=1,
            event_type=DomainEventType.SCHEDULE_TASK_UPDATED.value,
            entity_type="schedule_task",
            entity_id="t1",
            related_file_id=102,
            payload={},
            actor="user:web",
            timestamp_ms=1001,
        ),
        DomainEventRecorded(
            seq=3,
            user_id=1,
            event_type=DomainEventType.SCHEDULE_TASK_UPDATED.value,
            entity_type="schedule_task",
            entity_id="t1",
            related_file_id=103,
            payload={},
            actor="user:web",
            timestamp_ms=1002,
        ),
    ]

    ctx = await svc.load_linked_context(1, events)
    assert len(ctx["tasks"]) == 1
    assert ctx["tasks"][0]["task_id"] == "t1"
    # Only user 1's active file (101) is returned; deleted (102) and user 2's (103) are excluded.
    assert [p["file_id"] for p in ctx["linked_note_pages"]] == [101]


async def test_list_backfill_batch_paginates_newest_first_until_exhausted(
    session_manager: DatabaseSessionManager,
) -> None:
    async with session_manager.session() as session:
        for fid in (10, 20, 30):
            session.add(
                UserFileDO(
                    id=fid,
                    user_id=1,
                    file_name=f"Note{fid}.note",
                    is_folder="N",
                    is_active="Y",
                )
            )
            session.add(
                NotePageContentDO(
                    file_id=fid,
                    page_index=0,
                    page_id=f"P{fid}",
                    text_content=f"Content {fid}",
                )
            )
        await session.commit()

    svc = WikiSourceService(session_manager)
    batch1, cursor1 = await svc.list_backfill_batch(1, before_file_id=None, max_files=2)
    assert [d["related_file_id"] for d in batch1] == [30, 20]
    assert cursor1 == 20

    batch2, cursor2 = await svc.list_backfill_batch(
        1, before_file_id=cursor1, max_files=2
    )
    assert [d["related_file_id"] for d in batch2] == [10]
    assert cursor2 == 10

    batch3, cursor3 = await svc.list_backfill_batch(
        1, before_file_id=cursor2, max_files=2
    )
    assert batch3 == []
    assert cursor3 is None


async def test_list_task_snapshots_orders_most_recently_updated_first(
    session_manager: DatabaseSessionManager,
) -> None:
    async with session_manager.session() as session:
        session.add_all(
            [
                ScheduleTaskDO(user_id=1, task_id="old", title="Old", update_time=100),
                ScheduleTaskDO(user_id=1, task_id="new", title="New", update_time=300),
                ScheduleTaskDO(user_id=1, task_id="mid", title="Mid", update_time=200),
            ]
        )
        await session.commit()

    svc = WikiSourceService(session_manager)
    tasks = await svc.list_task_snapshots(1, limit=2)
    assert [t.task_id for t in tasks] == ["new", "mid"]


async def test_count_backfill_progress_tracks_remaining_and_total_per_user(
    session_manager: DatabaseSessionManager,
) -> None:
    async with session_manager.session() as session:
        for fid in (10, 20, 30):
            session.add(
                UserFileDO(
                    id=fid,
                    user_id=1,
                    file_name=f"Note{fid}.note",
                    is_folder="N",
                    is_active="Y",
                )
            )
            session.add(
                NotePageContentDO(
                    file_id=fid,
                    page_index=0,
                    page_id=f"P{fid}",
                    text_content=f"Content {fid}",
                )
            )
        # Unrelated user and inactive file must be excluded.
        session.add(
            UserFileDO(
                id=40, user_id=2, file_name="Other.note", is_folder="N", is_active="Y"
            )
        )
        session.add(
            NotePageContentDO(file_id=40, page_index=0, page_id="P40", text_content="x")
        )
        session.add(
            UserFileDO(
                id=50, user_id=1, file_name="Deleted.note", is_folder="N", is_active="N"
            )
        )
        session.add(
            NotePageContentDO(file_id=50, page_index=0, page_id="P50", text_content="y")
        )
        await session.commit()

    svc = WikiSourceService(session_manager)
    assert await svc.count_backfill_progress(1, before_file_id=None) == (3, 3)
    assert await svc.count_backfill_progress(1, before_file_id=20) == (1, 3)
    assert await svc.count_backfill_progress(1, before_file_id=10) == (0, 3)
    assert await svc.count_backfill_progress(2, before_file_id=None) == (1, 1)


async def test_get_backfill_overview_lists_next_files_and_untranscribed_notes(
    session_manager: DatabaseSessionManager,
) -> None:
    async with session_manager.session() as session:
        for fid in (10, 20, 30):
            session.add(
                UserFileDO(
                    id=fid,
                    user_id=1,
                    file_name=f"Note{fid}.note",
                    is_folder="N",
                    is_active="Y",
                )
            )
            session.add(
                NotePageContentDO(
                    file_id=fid,
                    page_index=0,
                    page_id=f"P{fid}",
                    text_content=f"Content {fid}",
                )
            )
        # Add a second non-blank page and a whitespace-only blank page on file 30.
        session.add_all(
            [
                NotePageContentDO(
                    file_id=30,
                    page_index=1,
                    page_id="P30_1",
                    text_content="Second page on 30",
                ),
                NotePageContentDO(
                    file_id=30,
                    page_index=2,
                    page_id="P30_2",
                    text_content="   \n\t ",
                ),
            ]
        )
        # Un-OCR'd .note file (counted in untranscribed_files) vs PDF (ignored).
        session.add_all(
            [
                UserFileDO(
                    id=35,
                    user_id=1,
                    file_name="Pending.note",
                    is_folder="N",
                    is_active="Y",
                ),
                UserFileDO(
                    id=36,
                    user_id=1,
                    file_name="Manual.pdf",
                    is_folder="N",
                    is_active="Y",
                ),
            ]
        )
        await session.commit()

    svc = WikiSourceService(session_manager)
    initial = await svc.get_backfill_overview(1, before_file_id=None, preview_limit=2)
    assert initial.total_files == 3
    assert initial.remaining_files == 3
    assert initial.total_pages == 4
    assert initial.remaining_pages == 4
    assert initial.untranscribed_files == 1
    assert initial.next_files == ["Note30.note", "Note20.note"]

    after_first = await svc.get_backfill_overview(1, before_file_id=20, preview_limit=5)
    assert after_first.remaining_files == 1
    assert after_first.remaining_pages == 1
    assert after_first.next_files == ["Note10.note"]

    done = await svc.get_backfill_overview(1, before_file_id=10, preview_limit=5)
    assert done.remaining_files == 0
    assert done.remaining_pages == 0
    assert done.next_files == []


async def test_resolve_source_metadata_returns_names_and_enforces_tenant_isolation(
    session_manager: DatabaseSessionManager,
) -> None:
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=501,
                    user_id=1,
                    file_name="Aurora_Spec.note",
                    is_folder="N",
                    is_active="Y",
                ),
                UserFileDO(
                    id=502,
                    user_id=2,
                    file_name="Secret_Other_User.note",
                    is_folder="N",
                    is_active="Y",
                ),
                UserFileDO(
                    id=503,
                    user_id=1,
                    file_name="Recycled.note",
                    is_folder="N",
                    is_active="N",
                ),
                NotePageContentDO(
                    file_id=501,
                    page_index=2,
                    page_id="P501_2",
                    text_content="Page 3 content",
                ),
                NotePageContentDO(
                    file_id=502,
                    page_index=0,
                    page_id="P502_0",
                    text_content="Other user content",
                ),
                ScheduleTaskDO(
                    user_id=1,
                    task_id="t-aurora",
                    title="Install UPS",
                    status="needsAction",
                    update_time=1000,
                ),
                ScheduleTaskDO(
                    user_id=2,
                    task_id="t-secret",
                    title="Other User Task",
                    status="needsAction",
                    update_time=1000,
                ),
            ]
        )
        await session.commit()

    svc = WikiSourceService(session_manager)
    meta = await svc.resolve_source_metadata(
        1,
        [
            WikiSourceRefDTO(
                source_type=WikiSourceType.NOTE_PAGE,
                source_key="501:P501_2",
                file_id=501,
            ),
            WikiSourceRefDTO(
                source_type=WikiSourceType.NOTE_PAGE,
                source_key="502:P502_0",
                file_id=502,
            ),
            WikiSourceRefDTO(
                source_type=WikiSourceType.NOTE_PAGE,
                source_key="503:P503_0",
                file_id=503,
            ),
            WikiSourceRefDTO(
                source_type=WikiSourceType.SCHEDULE_TASK, source_key="t-aurora"
            ),
            WikiSourceRefDTO(
                source_type=WikiSourceType.SCHEDULE_TASK, source_key="t-secret"
            ),
        ],
    )
    assert (
        meta[(WikiSourceType.NOTE_PAGE, "501:P501_2")].file_name == "Aurora_Spec.note"
    )
    assert meta[(WikiSourceType.NOTE_PAGE, "501:P501_2")].page_index == 2
    assert meta[(WikiSourceType.SCHEDULE_TASK, "t-aurora")].task_title == "Install UPS"
    # Tenant isolation and soft-deleted (recycled) file exclusion.
    assert (WikiSourceType.NOTE_PAGE, "502:P502_0") not in meta
    assert (WikiSourceType.NOTE_PAGE, "503:P503_0") not in meta
    assert (WikiSourceType.SCHEDULE_TASK, "t-secret") not in meta
