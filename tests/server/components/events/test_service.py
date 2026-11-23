"""Unit tests for EventLogService append, cursor querying, and retention pruning."""

import asyncio
import hashlib
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from supernote.models.base import BooleanEnum
from supernote.models.events import DomainEntityType, DomainEventType
from supernote.models.schedule import ScheduleTaskLinkDTO
from supernote.models.summary import AddSummaryDTO, AddSummaryGroupDTO, SummaryItem
from supernote.models.user import UserRegisterDTO
from supernote.server.ai.models.ocr import OcrModel
from supernote.server.components.events.models import encode_sync_token
from supernote.server.components.events.service import (
    SUBSCRIBED_DOMAIN_EVENTS,
    EventLogService,
)
from supernote.server.components.schedule.service import ScheduleService
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import (
    DomainEventRecorded,
    LocalEventBus,
    NotePagesDeltaEvent,
    NoteProcessingCompletedEvent,
    NoteProcessingFailedEvent,
    SummaryDeletedEvent,
    SummaryUpsertedEvent,
)
from supernote.server.exceptions import CursorExpiredError, InvalidInputError
from supernote.server.services.blob import BlobStorage
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules.ocr import OcrModule
from supernote.server.services.processor_modules.summary import SummaryModule
from supernote.server.services.summary import SummaryService
from supernote.server.services.user import UserService
from supernote.server.utils.paths import get_page_png_path


@pytest.fixture
def event_bus() -> LocalEventBus:
    return LocalEventBus()


@pytest.fixture
def event_log_service(
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    event_bus: LocalEventBus,
) -> EventLogService:
    return EventLogService(
        session_manager=session_manager,
        coordination_service=coordination_service,
        event_bus=event_bus,
        retention_days=90,
    )


async def test_append_persists_and_publishes_domain_event(
    event_log_service: EventLogService,
    event_bus: LocalEventBus,
) -> None:
    """Verify append commits monotonic seq rows and emits DomainEventRecorded."""
    published: list[DomainEventRecorded] = []

    async def on_recorded(ev: DomainEventRecorded) -> None:
        published.append(ev)

    event_bus.subscribe(DomainEventRecorded, on_recorded, inline=True)

    e1 = await event_log_service.append(
        user_id=1,
        event_type="vfs.created",
        entity_type="file",
        entity_id="100",
        related_file_id=100,
        actor="device:SN001",
        payload={"path": "/NOTE/a.note"},
        timestamp_ms=1_700_000_001_000,
    )
    e2 = await event_log_service.append(
        user_id=1,
        event_type="note.page_transcribed",
        entity_type="note_page",
        entity_id="100:0",
        related_file_id=100,
        actor="system:processor",
        payload={"page_index": 0, "current_text": "hello"},
        timestamp_ms=1_700_000_002_000,
    )

    assert e2.seq > e1.seq
    assert published == [e1, e2]


async def test_list_events_sync_tokens_filters_and_user_isolation(
    event_log_service: EventLogService,
) -> None:
    """Verify sync_token=None/empty, pagination, type globbing, file_id, and exclude_actor."""
    empty_page = await event_log_service.list_events(user_id=1)
    assert empty_page.events == []
    assert empty_page.next_sync_token is None
    assert empty_page.has_more is False

    ev1 = await event_log_service.append(
        user_id=1,
        event_type="vfs.created",
        entity_type="file",
        entity_id="10",
        related_file_id=10,
        actor="device:SN1",
    )
    ev2 = await event_log_service.append(
        user_id=2,
        event_type="vfs.created",
        entity_type="file",
        entity_id="20",
        related_file_id=20,
        actor="user:web",
    )
    ev3 = await event_log_service.append(
        user_id=1,
        event_type="note.page_transcribed",
        entity_type="note_page",
        entity_id="10:0",
        related_file_id=10,
        actor="system:processor",
    )
    ev4 = await event_log_service.append(
        user_id=1,
        event_type="schedule.task_created",
        entity_type="schedule_task",
        entity_id="t-1",
        actor="user:web",
    )
    assert ev1.seq < ev2.seq < ev3.seq < ev4.seq

    # User 1 sees only user 1 events; paginate 2 at a time
    page1 = await event_log_service.list_events(user_id=1, limit=2)
    assert [e.seq for e in page1.events] == [ev1.seq, ev3.seq]
    assert page1.has_more is True
    assert page1.next_sync_token == encode_sync_token(ev3.seq)
    assert page1.next_sync_token != str(ev3.seq)

    page2 = await event_log_service.list_events(
        user_id=1, sync_token=page1.next_sync_token, limit=2
    )
    assert [e.seq for e in page2.events] == [ev4.seq]
    assert page2.has_more is False
    assert page2.next_sync_token == encode_sync_token(ev4.seq)

    # Prefix type globbing + exact type matching
    filtered_types = await event_log_service.list_events(
        user_id=1, event_types=["note.*", "schedule.task_created"]
    )
    assert [e.seq for e in filtered_types.events] == [ev3.seq, ev4.seq]

    # When a filtered query has 0 matches, next_sync_token advances to user's latest seq
    no_match = await event_log_service.list_events(user_id=1, event_types=["summary.*"])
    assert no_match.events == []
    assert no_match.next_sync_token == encode_sync_token(ev4.seq)

    # file_id filter
    by_file = await event_log_service.list_events(user_id=1, file_id=10)
    assert [e.seq for e in by_file.events] == [ev1.seq, ev3.seq]


async def test_list_events_validation_errors(
    event_log_service: EventLogService,
) -> None:
    """Verify invalid sync tokens (including raw integers) and out-of-range limits raise InvalidInputError."""
    for bad_token in (
        "0",
        "100",
        "-1",
        "abc",
        "head",
        "!!!",
        "djE6MA",  # base64url("v1:0")
        f"{encode_sync_token(10)}=",
    ):
        with pytest.raises(InvalidInputError):
            await event_log_service.list_events(user_id=1, sync_token=bad_token)

    for bad_limit in (0, -5, 1001):
        with pytest.raises(InvalidInputError):
            await event_log_service.list_events(user_id=1, limit=bad_limit)


async def test_prune_expired_events_and_cursor_expiration(
    event_log_service: EventLogService,
) -> None:
    """Verify pruning deletes expired history and raises 410 only for sync_token < pruned_seq."""
    now_ms = int(time.time() * 1000)
    old1 = await event_log_service.append(
        user_id=1,
        event_type="vfs.created",
        entity_type="file",
        entity_id="1",
        timestamp_ms=now_ms - 10_000,
    )
    old2 = await event_log_service.append(
        user_id=1,
        event_type="vfs.moved",
        entity_type="file",
        entity_id="1",
        timestamp_ms=now_ms - 8_000,
    )
    recent = await event_log_service.append(
        user_id=1,
        event_type="vfs.deleted",
        entity_type="file",
        entity_id="1",
        timestamp_ms=now_ms - 1_000,
    )

    deleted = await event_log_service.prune_expired_events(max_age_ms=5_000)
    assert deleted == 2

    # sync_token < old2.seq is expired (410 Gone)
    with pytest.raises(CursorExpiredError) as exc_info:
        await event_log_service.list_events(
            user_id=1, sync_token=encode_sync_token(old1.seq)
        )
    assert exc_info.value.status_code == 410

    # sync_token == old2.seq is still valid because client already consumed up through old2.seq
    from_boundary = await event_log_service.list_events(
        user_id=1, sync_token=encode_sync_token(old2.seq)
    )
    assert [e.seq for e in from_boundary.events] == [recent.seq]

    # sync_token == None or "" always returns retained history without raising 410
    from_start = await event_log_service.list_events(user_id=1)
    assert [e.seq for e in from_start.events] == [recent.seq]
    from_empty = await event_log_service.list_events(user_id=1, sync_token="")
    assert [e.seq for e in from_empty.events] == [recent.seq]

    # Pruning again with no expired rows or disabled retention is a safe no-op
    assert await event_log_service.prune_expired_events(max_age_ms=5_000) == 0
    assert await event_log_service.prune_expired_events(max_age_ms=0) == 0
    assert await event_log_service.prune_expired_events() == 0


async def test_prune_disabled_when_retention_days_is_zero(
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
) -> None:
    """Verify retention_days=0 retains events indefinitely."""
    svc = EventLogService(
        session_manager=session_manager,
        coordination_service=coordination_service,
        retention_days=0,
    )
    await svc.append(
        user_id=1,
        event_type="vfs.created",
        entity_type="file",
        entity_id="1",
        timestamp_ms=1_000,
    )
    assert await svc.prune_expired_events() == 0


async def test_summary_domain_events_recorded(
    event_log_service: EventLogService,
    event_bus: LocalEventBus,
    session_manager: DatabaseSessionManager,
    user_service: UserService,
    storage_root: Path,
    blob_storage: BlobStorage,
) -> None:
    """Verify summary upserts, group cascade deletes, and file cleanup record summary.* events."""
    test_user = "summary_events@example.com"
    await user_service.register(UserRegisterDTO(email=test_user, password="a" * 32))
    test_user_id = await user_service.get_user_id(test_user)
    assert test_user_id is not None

    summary_service = SummaryService(user_service, session_manager, event_bus)
    file_service = FileService(
        storage_root, blob_storage, user_service, session_manager, event_bus
    )
    summary_module = SummaryModule(
        file_service=file_service,
        summary_service=summary_service,
        summary_model=None,
    )

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=501,
                user_id=test_user_id,
                file_name="notes.note",
                directory_id=0,
            )
        )
        await session.commit()

    group = await summary_service.add_group(
        test_user,
        AddSummaryGroupDTO(
            unique_identifier="grp-1",
            name="notes.note",
            md5_hash="g-md5",
        ),
    )
    leaf = await summary_service.add_summary(
        test_user,
        AddSummaryDTO(
            file_id=501,
            unique_identifier="leaf-1",
            parent_unique_identifier="grp-1",
            content="Summary text",
            source_path="/NOTE/notes.note",
            data_source="AI",
        ),
    )
    assert group.id is not None and leaf.id is not None

    # Deleting a group cascades a summary.deleted tombstone for both the group and its child leaf
    await summary_service.delete_group(test_user, group.id)

    page = await event_log_service.list_events(
        user_id=test_user_id, event_types=["summary.*"]
    )
    assert [
        (e.event_type, e.entity_type, e.entity_id, e.related_file_id)
        for e in page.events
    ] == [
        (
            DomainEventType.SUMMARY_UPSERTED,
            DomainEntityType.SUMMARY,
            str(group.id),
            None,
        ),
        (DomainEventType.SUMMARY_UPSERTED, DomainEntityType.SUMMARY, str(leaf.id), 501),
        (
            DomainEventType.SUMMARY_DELETED,
            DomainEntityType.SUMMARY,
            str(group.id),
            None,
        ),
        (DomainEventType.SUMMARY_DELETED, DomainEntityType.SUMMARY, str(leaf.id), 501),
    ]
    assert page.events[0].payload["summary"]["isSummaryGroup"] == "Y"
    assert page.events[1].payload["is_new"] is True
    assert page.events[3].payload == {
        "summary_id": str(leaf.id),
        "file_id": "501",
        "unique_identifier": "leaf-1",
        "is_summary_group": False,
    }

    # Recreate legacy per-file group + leaf and verify SummaryModule.cleanup_file emits summary.deleted tombstones
    group2 = await summary_service.add_group(
        test_user,
        AddSummaryGroupDTO(
            unique_identifier="notes.note-group",
            name="notes.note",
            md5_hash="g-md5",
        ),
    )
    leaf2 = await summary_service.add_summary(
        test_user,
        AddSummaryDTO(
            file_id=501,
            unique_identifier="legacy-501.note-summary",
            parent_unique_identifier="notes.note-group",
            content="Summary text 2",
        ),
    )
    before_cleanup = await event_log_service.list_events(user_id=test_user_id)
    await summary_module.cleanup_file(501, test_user_id, session_manager)

    after_cleanup = await event_log_service.list_events(
        user_id=test_user_id, sync_token=before_cleanup.next_sync_token
    )
    assert [
        (e.event_type, e.entity_id, e.payload["is_summary_group"])
        for e in after_cleanup.events
    ] == [
        (DomainEventType.SUMMARY_DELETED, str(leaf2.id), False),
        (DomainEventType.SUMMARY_DELETED, str(group2.id), True),
    ]

    # Device actor provenance via equipment_no
    await event_bus.publish(
        SummaryUpsertedEvent(
            user_id=test_user_id,
            summary=SummaryItem(
                id=999,
                unique_identifier="dev-sum",
                is_summary_group=BooleanEnum.NO,
            ),
            is_new=False,
            equipment_no="SN777",
        )
    )
    await event_bus.publish(
        SummaryDeletedEvent(
            user_id=test_user_id,
            summary_id=999,
            unique_identifier="dev-sum",
            equipment_no="SN777",
        )
    )
    dev_events = await event_log_service.list_events(
        user_id=test_user_id, sync_token=after_cleanup.next_sync_token
    )
    assert [e.actor for e in dev_events.events] == ["device:SN777", "device:SN777"]


async def test_vfs_file_and_folder_domain_events_recorded(
    event_log_service: EventLogService,
    event_bus: LocalEventBus,
    session_manager: DatabaseSessionManager,
    user_service: UserService,
    storage_root: Path,
    blob_storage: BlobStorage,
) -> None:
    """Verify VFS create, content update, MD5 no-op suppression, and recursive folder mutations."""
    test_user = "vfs_events@example.com"
    await user_service.register(UserRegisterDTO(email=test_user, password="a" * 32))
    test_user_id = await user_service.get_user_id(test_user)
    assert test_user_id is not None

    file_service = FileService(
        storage_root, blob_storage, user_service, session_manager, event_bus
    )

    # Create a subfolder under /Note
    note_dir = await file_service.get_file_info(test_user, "Note")
    assert note_dir is not None
    sub_dir = await file_service.create_directory_by_id(
        test_user, note_dir.id, "Projects"
    )

    # Upload a .note file into /Note/Projects
    blob1 = b"note-v1"
    md5_1 = hashlib.md5(blob1).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "inner-v1", blob1)
    await file_service.upload_finish_web(
        test_user, sub_dir.id, "todo.note", md5_1, "inner-v1"
    )
    note_info = await file_service.get_file_info(test_user, "Note/Projects/todo.note")
    assert note_info is not None

    # Re-uploading identical MD5 suppresses duplicate vfs.content_updated
    await file_service.upload_finish_web(
        test_user, sub_dir.id, "todo.note", md5_1, "inner-v1"
    )

    # Uploading modified content records vfs.content_updated with old_md5 and new_md5
    blob2 = b"note-v2-updated"
    md5_2 = hashlib.md5(blob2).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "inner-v2", blob2)
    await file_service.upload_finish_web(
        test_user, sub_dir.id, "todo.note", md5_2, "inner-v2"
    )

    p1 = await event_log_service.list_events(
        user_id=test_user_id, event_types=["vfs.*"]
    )
    assert [(e.event_type, e.entity_id, e.related_file_id) for e in p1.events] == [
        (DomainEventType.VFS_CREATED, str(sub_dir.id), None),
        (DomainEventType.VFS_CREATED, str(note_info.id), note_info.id),
        (DomainEventType.VFS_CONTENT_UPDATED, str(note_info.id), note_info.id),
    ]
    assert p1.events[2].payload["old_md5"] == md5_1
    assert p1.events[2].payload["new_md5"] == md5_2

    # Rename folder -> emits vfs.moved for the folder
    await file_service.rename_item(test_user, sub_dir.id, "Roadmap")
    p2 = await event_log_service.list_events(
        user_id=test_user_id, sync_token=p1.next_sync_token
    )
    assert [
        (
            e.event_type,
            e.entity_id,
            e.payload["original_full_path"],
            e.payload["new_full_path"],
        )
        for e in p2.events
    ] == [
        (
            DomainEventType.VFS_MOVED,
            str(sub_dir.id),
            "NOTE/Note/Projects",
            "NOTE/Note/Roadmap",
        ),
    ]

    # Copy folder -> emits vfs.copied for the folder
    copied_dir = await file_service.copy_item(
        test_user, sub_dir.id, "NOTE/Note/RoadmapCopy", autorename=True
    )
    p3 = await event_log_service.list_events(
        user_id=test_user_id, sync_token=p2.next_sync_token
    )
    assert len(p3.events) == 1
    assert p3.events[0].event_type == DomainEventType.VFS_COPIED
    assert p3.events[0].entity_id == str(copied_dir.id)
    assert p3.events[0].payload["source_id"] == str(sub_dir.id)
    assert p3.events[0].payload["original_full_path"] == "NOTE/Note/Roadmap"

    # Delete folder -> emits vfs.deleted for the folder
    await file_service.delete_item(test_user, copied_dir.id)
    p4 = await event_log_service.list_events(
        user_id=test_user_id, sync_token=p3.next_sync_token
    )
    assert [e.event_type for e in p4.events] == [DomainEventType.VFS_DELETED]
    assert p4.events[0].entity_id == str(copied_dir.id)


async def test_schedule_task_domain_events_recorded(
    event_log_service: EventLogService,
    event_bus: LocalEventBus,
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify schedule task create, semantic update (suppressing sort-only), and delete events."""
    schedule_service = ScheduleService(session_manager, event_bus)
    uid = 77

    group = await schedule_service.create_group(uid, "Action Items")
    link_b64 = ScheduleTaskLinkDTO(
        app_name="Note",
        path="/Note/Todo.note",
        page=1,
        file_id="901",
        page_id="P1",
    ).to_b64()

    task = await schedule_service.create_task(
        uid,
        group_id=group.task_list_id,
        title="Ship slice",
        detail="Minimal PR",
        links=link_b64,
    )

    # Sort-only updates do not emit schedule.task_updated
    await schedule_service.update_task(uid, task.task_id, sort=5, sort_time=1000)
    await schedule_service.batch_update_tasks(
        uid,
        [{"task_id": task.task_id, "sort": 10}],
        task_list_id=group.task_list_id,
    )

    # Semantic update emits schedule.task_updated with changed_fields [old, new]
    await schedule_service.update_task(
        uid,
        task.task_id,
        status="completed",
        completed_time=1710000005000,
        update_time=1710000006000,
    )

    # Batch update clearing links still associates related_file_id via changed_fields["links"][0]
    await schedule_service.batch_update_tasks(
        uid,
        [
            {
                "task_id": task.task_id,
                "title": "Ship slice v2",
                "links": None,
                "update_time": 1710000008000,
            }
        ],
        task_list_id=group.task_list_id,
    )

    # Deleting the group cascades schedule.task_deleted for tasks in the group
    await schedule_service.delete_group(uid, group.task_list_id)

    page = await event_log_service.list_events(user_id=uid, event_types=["schedule.*"])
    assert [
        (e.event_type, e.entity_type, e.entity_id, e.related_file_id)
        for e in page.events
    ] == [
        (
            DomainEventType.SCHEDULE_TASK_CREATED,
            DomainEntityType.SCHEDULE_TASK,
            task.task_id,
            901,
        ),
        (
            DomainEventType.SCHEDULE_TASK_UPDATED,
            DomainEntityType.SCHEDULE_TASK,
            task.task_id,
            901,
        ),
        (
            DomainEventType.SCHEDULE_TASK_UPDATED,
            DomainEntityType.SCHEDULE_TASK,
            task.task_id,
            901,
        ),
        (
            DomainEventType.SCHEDULE_TASK_DELETED,
            DomainEntityType.SCHEDULE_TASK,
            task.task_id,
            None,
        ),
    ]
    assert page.events[0].payload == {
        "task_id": task.task_id,
        "task_list_id": group.task_list_id,
        "title": "Ship slice",
        "detail": "Minimal PR",
        "status": "needsAction",
        "due_time": None,
        "links": link_b64,
    }
    assert page.events[1].payload == {
        "task_id": task.task_id,
        "task_list_id": group.task_list_id,
        "title": "Ship slice",
        "detail": "Minimal PR",
        "status": "completed",
        "due_time": None,
        "links": link_b64,
        "changed_fields": {
            "status": ["needsAction", "completed"],
            "completed_time": [None, 1710000005000],
        },
    }
    assert page.events[2].payload == {
        "task_id": task.task_id,
        "task_list_id": group.task_list_id,
        "title": "Ship slice v2",
        "detail": "Minimal PR",
        "status": "completed",
        "due_time": None,
        "links": None,
        "changed_fields": {
            "title": ["Ship slice", "Ship slice v2"],
            "links": [link_b64, None],
        },
    }
    assert page.events[3].payload == {
        "task_id": task.task_id,
        "task_list_id": group.task_list_id,
        "title": "Ship slice v2",
        "status": "completed",
        "links": None,
    }


async def test_note_processing_domain_events_recorded(
    event_log_service: EventLogService,
    event_bus: LocalEventBus,
    session_manager: DatabaseSessionManager,
    user_service: UserService,
    storage_root: Path,
    blob_storage: BlobStorage,
) -> None:
    """Verify note.pages_delta, note.page_transcribed, and note.processing_* events."""
    test_user = "note_events@example.com"
    await user_service.register(UserRegisterDTO(email=test_user, password="a" * 32))
    uid = await user_service.get_user_id(test_user)
    assert uid is not None

    file_service = FileService(
        storage_root, blob_storage, user_service, session_manager, event_bus
    )

    class _StubOcrModel(OcrModel):
        @property
        def provider(self) -> str:
            return "stub"

        @property
        def model_id(self) -> str:
            return "stub-ocr"

        async def extract_text(self, png_data: bytes, prompt: str) -> str:
            return "Transcribed bullet item"

    ocr_module = OcrModule(file_service=file_service, ocr_model=_StubOcrModel())

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=801,
                user_id=uid,
                file_name="Journal.note",
                directory_id=0,
            )
        )
        session.add(
            NotePageContentDO(
                file_id=801,
                page_index=0,
                page_id="P20261115000001abcdef",
                content_hash="h1",
            )
        )
        await session.commit()

    await event_bus.publish(
        NotePagesDeltaEvent(
            user_id=uid,
            file_id=801,
            file_path="Journal.note",
            added_pages=["P20261115000001abcdef"],
        )
    )

    await blob_storage.put(
        CACHE_BUCKET,
        get_page_png_path(801, "P20261115000001abcdef"),
        b"fake-png",
    )
    await ocr_module.process(
        801,
        session_manager,
        page_index=0,
        page_id="P20261115000001abcdef",
    )

    await event_bus.publish(
        NoteProcessingCompletedEvent(
            user_id=uid,
            file_id=801,
            file_path="Journal.note",
        )
    )
    await event_bus.publish(
        NoteProcessingFailedEvent(
            user_id=uid,
            file_id=801,
            file_path="Journal.note",
            module_name="OcrModule",
            error="rate limited",
            page_id="P20261115000001abcdef",
        )
    )

    page = await event_log_service.list_events(user_id=uid, event_types=["note.*"])
    assert [
        (e.event_type, e.entity_type, e.entity_id, e.related_file_id, e.actor)
        for e in page.events
    ] == [
        (
            DomainEventType.NOTE_PAGES_DELTA,
            DomainEntityType.FILE,
            "801",
            801,
            "system:processor",
        ),
        (
            DomainEventType.NOTE_PAGE_TRANSCRIBED,
            DomainEntityType.NOTE_PAGE,
            "801:P20261115000001abcdef",
            801,
            "system:processor",
        ),
        (
            DomainEventType.NOTE_PROCESSING_COMPLETED,
            DomainEntityType.FILE,
            "801",
            801,
            "system:processor",
        ),
        (
            DomainEventType.NOTE_PROCESSING_FAILED,
            DomainEntityType.FILE,
            "801",
            801,
            "system:processor",
        ),
    ]
    assert page.events[0].payload["added_pages"] == ["P20261115000001abcdef"]
    assert page.events[1].payload["text_content"] == "Transcribed bullet item"
    assert page.events[3].payload["module_name"] == "OcrModule"


def test_all_domain_event_types_are_subscribed() -> None:
    """Verify every DomainEventType is backed by a subscribed DomainEvent class."""
    subscribed_types = {cls.EVENT_TYPE for cls in SUBSCRIBED_DOMAIN_EVENTS}
    assert subscribed_types == set(DomainEventType)


async def test_list_events_exclude_actors_filters_and_advances_cursor(
    event_log_service: EventLogService,
) -> None:
    """Verify exclude_actors omits matching actors while advancing next_sync_token past them."""
    ev_web = await event_log_service.append(
        user_id=55,
        event_type=DomainEventType.SCHEDULE_TASK_CREATED,
        entity_type=DomainEntityType.SCHEDULE_TASK,
        entity_id="t1",
        actor="user:web",
    )
    ev_agent = await event_log_service.append(
        user_id=55,
        event_type=DomainEventType.SCHEDULE_TASK_CREATED,
        entity_type=DomainEntityType.SCHEDULE_TASK,
        entity_id="t2",
        actor="api_key:agent_1",
    )
    ev_device = await event_log_service.append(
        user_id=55,
        event_type=DomainEventType.SCHEDULE_TASK_CREATED,
        entity_type=DomainEntityType.SCHEDULE_TASK,
        entity_id="t3",
        actor="device:SN001",
    )
    ev_agent_tail = await event_log_service.append(
        user_id=55,
        event_type=DomainEventType.SCHEDULE_TASK_CREATED,
        entity_type=DomainEntityType.SCHEDULE_TASK,
        entity_id="t4",
        actor="api_key:agent_1",
    )

    page1 = await event_log_service.list_events(
        user_id=55, exclude_actors=["api_key:agent_1"], limit=1
    )
    assert [e.seq for e in page1.events] == [ev_web.seq]
    assert page1.has_more is True

    page2 = await event_log_service.list_events(
        user_id=55,
        sync_token=page1.next_sync_token,
        exclude_actors=["api_key:agent_1"],
        limit=1,
    )
    assert [e.seq for e in page2.events] == [ev_device.seq]
    assert page2.has_more is False
    assert ev_agent.seq < ev_device.seq

    # Next poll sees no new non-excluded events and advances next_sync_token past ev_agent_tail.
    after = await event_log_service.list_events(
        user_id=55,
        sync_token=page2.next_sync_token,
        exclude_actors=["api_key:agent_1"],
    )
    assert after.events == []
    assert after.next_sync_token == encode_sync_token(ev_agent_tail.seq)


def test_event_log_service_rejects_non_positive_prune_interval(
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
) -> None:
    """Verify non-positive prune_interval_seconds raises ValueError."""
    with pytest.raises(ValueError, match="prune_interval_seconds"):
        EventLogService(
            session_manager=session_manager,
            coordination_service=coordination_service,
            prune_interval_seconds=0,
        )


async def test_event_log_service_zero_retention_skips_background_pruner(
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
) -> None:
    """Verify retention_days=0 keeps old events untouched even when started."""
    service = EventLogService(
        session_manager=session_manager,
        coordination_service=coordination_service,
        retention_days=0,
        prune_interval_seconds=0.01,
    )
    old_ts = int(time.time() * 1000) - (100 * 86_400_000)
    await service.append(
        user_id=76,
        event_type="vfs.created",
        entity_type="file",
        entity_id="keep",
        timestamp_ms=old_ts,
    )
    await service.start()
    await asyncio.sleep(0.03)
    await service.stop()

    page = await service.list_events(user_id=76)
    assert len(page.events) == 1


async def test_event_log_service_background_pruner_deletes_expired_events(
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
) -> None:
    """Verify start/stop periodically prunes expired events and is idempotent."""
    service = EventLogService(
        session_manager=session_manager,
        coordination_service=coordination_service,
        retention_days=1,
        prune_interval_seconds=0.02,
    )
    old_ts = int(time.time() * 1000) - (2 * 86_400_000)
    await service.append(
        user_id=77,
        event_type="vfs.created",
        entity_type="file",
        entity_id="old",
        timestamp_ms=old_ts,
    )
    await service.start()
    await service.start()  # idempotent second start

    for _ in range(50):
        if not (await service.list_events(user_id=77)).events:
            break
        await asyncio.sleep(0.01)

    assert (await service.list_events(user_id=77)).events == []
    await service.stop()
    await service.stop()  # idempotent second stop


async def test_event_log_service_background_pruner_recovers_from_transient_error(
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
) -> None:
    """Verify a transient exception in prune_expired_events does not kill the loop."""
    service = EventLogService(
        session_manager=session_manager,
        coordination_service=coordination_service,
        retention_days=1,
        prune_interval_seconds=0.01,
    )
    calls = 0
    recovered = asyncio.Event()

    async def flaky_prune() -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient db error")
        recovered.set()
        return 0

    with patch.object(service, "prune_expired_events", side_effect=flaky_prune):
        await service.start()
        try:
            await asyncio.wait_for(recovered.wait(), timeout=1.0)
        finally:
            await service.stop()

    assert calls >= 2
