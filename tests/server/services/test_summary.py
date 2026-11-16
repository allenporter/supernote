"""Unit tests for SummaryService."""

import asyncio
import hashlib
import math
import time
from dataclasses import replace

import pytest
from sqlalchemy import select, update

from supernote.models.base import BooleanEnum
from supernote.models.summary import (
    AddSummaryDTO,
    AddSummaryGroupDTO,
    QuerySummaryDTO,
    QuerySummaryGroupDTO,
    UpdateSummaryDTO,
    UpdateSummaryGroupDTO,
)
from supernote.models.user import UserRegisterDTO
from supernote.server.constants import RECYCLE_RETENTION_MS
from supernote.server.db.models.summary import SummaryDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import (
    BlobCleanupEvent,
    Event,
    LocalEventBus,
    SummaryDeletedEvent,
    SummaryTagDeletedEvent,
    SummaryTagUpsertedEvent,
    SummaryUpsertedEvent,
)
from supernote.server.exceptions import SummaryNotFound
from supernote.server.services.summary import SummaryService
from supernote.server.services.user import UserService

USER_EMAIL = "test@example.com"


@pytest.fixture
def event_bus() -> LocalEventBus:
    """Real LocalEventBus for verifying published domain events."""
    return LocalEventBus()


@pytest.fixture
def published_events(event_bus: LocalEventBus) -> list[Event]:
    """Capture BlobCleanupEvents published on the LocalEventBus."""
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    event_bus.subscribe(BlobCleanupEvent, capture)
    return events


@pytest.fixture
async def summary_service(
    user_service: UserService,
    session_manager: DatabaseSessionManager,
    event_bus: LocalEventBus,
) -> SummaryService:
    """Create a SummaryService bound to the test session manager with a registered test user."""
    await user_service.register(UserRegisterDTO(email=USER_EMAIL, password="a" * 32))
    return SummaryService(
        user_service=user_service,
        session_manager=session_manager,
        event_bus=event_bus,
    )


async def test_tag_crud_and_not_found_errors(
    summary_service: SummaryService,
) -> None:
    """Verify tag creation, update, deletion, and not-found error handling."""
    tag = await summary_service.add_tag(USER_EMAIL, "Important")
    assert tag.id is not None
    assert tag.name == "Important"

    assert await summary_service.update_tag(USER_EMAIL, tag.id, "Urgent")
    tags = await summary_service.list_tags(USER_EMAIL)
    assert [t.name for t in tags] == ["Urgent"]

    assert await summary_service.delete_tag(USER_EMAIL, tag.id)
    assert await summary_service.list_tags(USER_EMAIL) == []

    with pytest.raises(SummaryNotFound):
        await summary_service.update_tag(USER_EMAIL, 99999, "Missing")

    with pytest.raises(SummaryNotFound):
        await summary_service.delete_tag(USER_EMAIL, 99999)


async def test_summary_crud_and_lookup_helpers(
    summary_service: SummaryService,
) -> None:
    """Verify summary creation, updates, UUID/file lookups, and not-found errors."""
    created = await summary_service.add_summary(
        USER_EMAIL,
        AddSummaryDTO(
            file_id=42,
            unique_identifier="sum-uuid-1",
            parent_unique_identifier="grp-uuid-1",
            content="Initial content",
            source_path="/Note/Test.note",
            data_source="OCR",
            tags="t1",
            metadata='{"k": "v"}',
        ),
    )
    assert created.id is not None
    assert created.unique_identifier == "sum-uuid-1"

    by_uuid = await summary_service.get_summary_by_uuid(USER_EMAIL, "sum-uuid-1")
    assert by_uuid == created
    assert await summary_service.get_summary_by_uuid(USER_EMAIL, "missing-uuid") is None
    assert await summary_service.get_summary_by_uuid(USER_EMAIL, "") is None

    for_file = await summary_service.list_summaries_for_file_internal(USER_EMAIL, 42)
    assert for_file == [created]

    assert await summary_service.update_summary(
        USER_EMAIL,
        UpdateSummaryDTO(
            id=created.id,
            parent_unique_identifier="grp-uuid-2",
            content="Updated content",
            source_path="/Note/Moved.note",
            data_source="USER",
            source_type=2,
            tags="t2",
            metadata='{"k": "v2"}',
            comment_str="Updated comment",
            comment_handwrite_name="comment_hw.bin",
            handwrite_inner_name="inner_hw.bin",
            handwrite_md5="hw-md5-2",
            last_modified_time=1700000005000,
            md5_hash="custom-md5",
            author="Alice",
        ),
    )
    fetched = await summary_service.get_summary(USER_EMAIL, created.id)
    assert fetched == replace(
        created,
        parent_unique_identifier="grp-uuid-2",
        content="Updated content",
        source_path="/Note/Moved.note",
        data_source="USER",
        source_type=2,
        tags="t2",
        metadata='{"k": "v2"}',
        comment_str="Updated comment",
        comment_handwrite_name="comment_hw.bin",
        handwrite_inner_name="inner_hw.bin",
        handwrite_md5="hw-md5-2",
        last_modified_time=1700000005000,
        md5_hash="custom-md5",
        author="Alice",
        update_time=fetched.update_time,
    )

    assert await summary_service.update_summary(
        USER_EMAIL,
        UpdateSummaryDTO(id=created.id, content="Rehashed content"),
    )
    rehashed = await summary_service.get_summary(USER_EMAIL, created.id)
    assert rehashed.md5_hash == hashlib.md5(b"Rehashed content").hexdigest()
    assert rehashed.last_modified_time is not None
    assert rehashed.last_modified_time > 1700000005000
    infos = await summary_service.list_summary_infos(
        USER_EMAIL, QuerySummaryDTO(ids=[created.id])
    )
    assert len(infos) == 1
    assert infos[0].last_modified_time == rehashed.last_modified_time

    assert await summary_service.delete_summary(USER_EMAIL, created.id)

    with pytest.raises(SummaryNotFound):
        await summary_service.update_summary(
            USER_EMAIL, UpdateSummaryDTO(id=99999, content="Missing")
        )

    with pytest.raises(SummaryNotFound):
        await summary_service.delete_summary(USER_EMAIL, 99999)

    with pytest.raises(SummaryNotFound):
        await summary_service.get_summary(USER_EMAIL, 99999)


async def test_group_crud_and_fallback_lookup_by_id(
    summary_service: SummaryService,
) -> None:
    """Verify group creation, update by UUID and ID fallback, and not-found errors."""
    group = await summary_service.add_group(
        USER_EMAIL,
        AddSummaryGroupDTO(
            unique_identifier="group-uuid-1",
            name="Group 1",
            md5_hash="h1",
            description="Desc 1",
        ),
    )
    assert group.id is not None
    assert group.creation_time is not None
    assert group.last_modified_time is not None

    assert await summary_service.update_group(
        USER_EMAIL,
        UpdateSummaryGroupDTO(
            id=group.id,
            unique_identifier=None,
            name="Group 1 Updated",
            description="Desc 2",
            metadata='{"group_meta": true}',
            comment_str="Group comment",
            comment_handwrite_name="group_hw.bin",
            handwrite_inner_name="group_inner_hw.bin",
            md5_hash="h2",
            last_modified_time=1700000010000,
        ),
    )
    groups = await summary_service.list_groups(USER_EMAIL, QuerySummaryGroupDTO())
    assert len(groups) == 1
    assert groups[0] == replace(
        group,
        name="Group 1 Updated",
        description="Desc 2",
        metadata='{"group_meta": true}',
        comment_str="Group comment",
        comment_handwrite_name="group_hw.bin",
        handwrite_inner_name="group_inner_hw.bin",
        md5_hash="h2",
        last_modified_time=1700000010000,
        update_time=groups[0].update_time,
    )

    assert await summary_service.update_group(
        USER_EMAIL,
        UpdateSummaryGroupDTO(id=group.id, md5_hash="h2-auto-ts"),
    )
    refreshed_group = await summary_service.get_summary(USER_EMAIL, group.id)
    assert refreshed_group.last_modified_time is not None
    assert refreshed_group.last_modified_time > 1700000010000

    with pytest.raises(SummaryNotFound):
        await summary_service.update_group(
            USER_EMAIL,
            UpdateSummaryGroupDTO(
                id=99999,
                unique_identifier="missing-group-uuid",
                md5_hash="h3",
            ),
        )


@pytest.mark.parametrize("total_items", [0, 1, 6, 20, 25])
async def test_pagination_and_unpaginated_queries(
    summary_service: SummaryService,
    total_items: int,
) -> None:
    """Verify paginating with variable page sizes reconstructs the exact item set across SummaryService methods."""
    created_ids: list[int] = []
    parent_a_ids: list[int] = []
    for idx in range(total_items):
        parent_uuid = "parent-a" if idx % 2 == 0 else "parent-b"
        item = await summary_service.add_summary(
            USER_EMAIL,
            AddSummaryDTO(
                unique_identifier=f"svc-sum-{total_items}-{idx}",
                parent_unique_identifier=parent_uuid,
                content=f"Content {idx}",
            ),
        )
        assert item.id is not None
        created_ids.append(item.id)
        if parent_uuid == "parent-a":
            parent_a_ids.append(item.id)

    created_group_ids: list[int] = []
    for idx in range(total_items):
        group = await summary_service.add_group(
            USER_EMAIL,
            AddSummaryGroupDTO(
                unique_identifier=f"svc-grp-{total_items}-{idx}",
                name=f"Grp {idx}",
                md5_hash=f"gh-{idx}",
            ),
        )
        assert group.id is not None
        created_group_ids.append(group.id)

    assert await summary_service.count_summaries(USER_EMAIL) == total_items
    assert await summary_service.count_summaries(
        USER_EMAIL, parent_uuid="parent-a"
    ) == len(parent_a_ids)
    subset_ids = created_ids[:3]
    assert await summary_service.count_summaries(USER_EMAIL, ids=subset_ids) == len(
        subset_ids
    )
    assert await summary_service.count_groups(USER_EMAIL) == total_items

    for unpaginated_size in (None, 0):
        all_summaries = await summary_service.list_summaries(
            USER_EMAIL, page=0, size=unpaginated_size
        )
        assert [s.id for s in all_summaries] == created_ids

        all_infos = await summary_service.list_summary_infos(
            USER_EMAIL, QuerySummaryDTO(page=0, size=unpaginated_size)
        )
        assert [i.id for i in all_infos] == created_ids

        by_ids = await summary_service.list_summaries_by_id(
            USER_EMAIL,
            QuerySummaryDTO(ids=created_ids, page=0, size=unpaginated_size),
        )
        assert [s.id for s in by_ids] == created_ids

        all_groups = await summary_service.list_groups(
            USER_EMAIL, QuerySummaryGroupDTO(page=0, size=unpaginated_size)
        )
        assert [g.id for g in all_groups] == created_group_ids

    for page_size in (1, 3, 10, 20, 30):
        total_pages = max(1, math.ceil(total_items / page_size))
        collected_summaries: list[int] = []
        collected_infos: list[int] = []
        collected_by_id: list[int] = []
        collected_groups: list[int] = []

        for page in range(1, total_pages + 1):
            page_summaries = await summary_service.list_summaries(
                USER_EMAIL, page=page, size=page_size
            )
            assert len(page_summaries) <= page_size
            collected_summaries.extend(s.id for s in page_summaries if s.id is not None)

            page_infos = await summary_service.list_summary_infos(
                USER_EMAIL, QuerySummaryDTO(page=page, size=page_size)
            )
            assert len(page_infos) <= page_size
            collected_infos.extend(i.id for i in page_infos if i.id is not None)

            page_by_id = await summary_service.list_summaries_by_id(
                USER_EMAIL,
                QuerySummaryDTO(ids=created_ids, page=page, size=page_size),
            )
            assert len(page_by_id) <= page_size
            collected_by_id.extend(s.id for s in page_by_id if s.id is not None)

            page_groups = await summary_service.list_groups(
                USER_EMAIL, QuerySummaryGroupDTO(page=page, size=page_size)
            )
            assert len(page_groups) <= page_size
            collected_groups.extend(g.id for g in page_groups if g.id is not None)

        assert collected_summaries == created_ids
        assert collected_infos == created_ids
        assert collected_by_id == created_ids
        assert collected_groups == created_group_ids

        assert (
            await summary_service.list_summaries(
                USER_EMAIL, page=total_pages + 1, size=page_size
            )
            == []
        )
        assert (
            await summary_service.list_groups(
                USER_EMAIL,
                QuerySummaryGroupDTO(page=total_pages + 1, size=page_size),
            )
            == []
        )


async def test_delete_group_cascades_to_child_summaries(
    summary_service: SummaryService,
) -> None:
    """Verify delete_group cascades soft-deletion to child summaries in that group while preserving others."""
    group = await summary_service.add_group(
        USER_EMAIL,
        AddSummaryGroupDTO(
            unique_identifier="grp-cascade-1",
            name="Cascade Group",
            md5_hash="gh1",
        ),
    )
    other_group = await summary_service.add_group(
        USER_EMAIL,
        AddSummaryGroupDTO(
            unique_identifier="grp-other-1",
            name="Other Group",
            md5_hash="gh2",
        ),
    )
    assert group.id is not None and other_group.id is not None

    child = await summary_service.add_summary(
        USER_EMAIL,
        AddSummaryDTO(
            unique_identifier="child-sum-1",
            parent_unique_identifier="grp-cascade-1",
            content="Child summary",
        ),
    )
    other_child = await summary_service.add_summary(
        USER_EMAIL,
        AddSummaryDTO(
            unique_identifier="other-sum-1",
            parent_unique_identifier="grp-other-1",
            content="Other summary",
        ),
    )
    assert child.id is not None and other_child.id is not None

    await summary_service.delete_group(USER_EMAIL, group.id)
    assert [
        g.id
        for g in await summary_service.list_groups(USER_EMAIL, QuerySummaryGroupDTO())
    ] == [other_group.id]
    assert [s.id for s in await summary_service.list_summaries(USER_EMAIL)] == [
        other_child.id
    ]


async def test_summary_service_publishes_domain_events_on_mutations(
    user_service: UserService,
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify SummaryService emits domain events on tag, group, and summary mutations and skips failed mutations."""
    await user_service.register(UserRegisterDTO(email=USER_EMAIL, password="a" * 32))
    user_id = await user_service.get_user_id(USER_EMAIL)
    event_bus = LocalEventBus()
    published: list[Event] = []

    async def on_event(event: Event) -> None:
        published.append(event)

    event_bus.subscribe(SummaryTagUpsertedEvent, on_event)
    event_bus.subscribe(SummaryTagDeletedEvent, on_event)
    event_bus.subscribe(SummaryUpsertedEvent, on_event)
    event_bus.subscribe(SummaryDeletedEvent, on_event)

    service = SummaryService(
        user_service=user_service,
        session_manager=session_manager,
        event_bus=event_bus,
    )

    tag = await service.add_tag(USER_EMAIL, "Tag A")
    assert tag.id is not None
    await asyncio.sleep(0)
    assert published == [
        SummaryTagUpsertedEvent(user_id=user_id, tag=tag, is_new=True),
    ]
    published.clear()

    await service.update_tag(USER_EMAIL, tag.id, "Tag B")
    await asyncio.sleep(0)
    updated_tags = await service.list_tags(USER_EMAIL)
    assert published == [
        SummaryTagUpsertedEvent(
            user_id=user_id,
            tag=updated_tags[0],
            is_new=False,
        ),
    ]
    published.clear()

    await service.delete_tag(USER_EMAIL, tag.id)
    await asyncio.sleep(0)
    assert published == [
        SummaryTagDeletedEvent(user_id=user_id, tag_id=tag.id),
    ]
    published.clear()

    group = await service.add_group(
        USER_EMAIL,
        AddSummaryGroupDTO(
            unique_identifier="grp-ev-1",
            name="Group Event 1",
            md5_hash="gh-ev-1",
        ),
    )
    assert group.id is not None
    await asyncio.sleep(0)
    assert published == [
        SummaryUpsertedEvent(user_id=user_id, summary=group, is_new=True),
    ]
    published.clear()

    await service.update_group(
        USER_EMAIL,
        UpdateSummaryGroupDTO(
            id=group.id,
            unique_identifier="grp-ev-1",
            name="Group Event Updated",
            md5_hash="gh-ev-2",
        ),
    )
    await asyncio.sleep(0)
    updated_group = await service.get_summary(USER_EMAIL, group.id)
    assert published == [
        SummaryUpsertedEvent(user_id=user_id, summary=updated_group, is_new=False),
    ]
    published.clear()

    summary = await service.add_summary(
        USER_EMAIL,
        AddSummaryDTO(
            unique_identifier="sum-ev-1",
            parent_unique_identifier="grp-ev-1",
            content="Summary event content",
        ),
    )
    assert summary.id is not None
    await asyncio.sleep(0)
    assert published == [
        SummaryUpsertedEvent(user_id=user_id, summary=summary, is_new=True),
    ]
    published.clear()

    await service.update_summary(
        USER_EMAIL,
        UpdateSummaryDTO(id=summary.id, content="Updated summary event content"),
    )
    await asyncio.sleep(0)
    updated_summary = await service.get_summary(USER_EMAIL, summary.id)
    assert published == [
        SummaryUpsertedEvent(user_id=user_id, summary=updated_summary, is_new=False),
    ]
    published.clear()

    await service.delete_summary(USER_EMAIL, summary.id)
    await asyncio.sleep(0)
    assert published == [
        SummaryDeletedEvent(
            user_id=user_id,
            summary_id=summary.id,
            is_summary_group=False,
            unique_identifier="sum-ev-1",
        ),
    ]
    published.clear()

    await service.delete_group(USER_EMAIL, group.id)
    await asyncio.sleep(0)
    assert published == [
        SummaryDeletedEvent(
            user_id=user_id,
            summary_id=group.id,
            is_summary_group=True,
            unique_identifier="grp-ev-1",
        ),
    ]
    published.clear()

    with pytest.raises(SummaryNotFound):
        await service.update_tag(USER_EMAIL, 99999, "Missing")
    with pytest.raises(SummaryNotFound):
        await service.delete_tag(USER_EMAIL, 99999)
    with pytest.raises(SummaryNotFound):
        await service.update_group(
            USER_EMAIL,
            UpdateSummaryGroupDTO(id=99999, unique_identifier="missing", md5_hash="h"),
        )
    with pytest.raises(SummaryNotFound):
        await service.update_summary(USER_EMAIL, UpdateSummaryDTO(id=99999))
    with pytest.raises(SummaryNotFound):
        await service.delete_summary(USER_EMAIL, 99999)
    await asyncio.sleep(0)
    assert published == []


async def test_handwrite_replacement_and_expired_summary_purge_publish_blob_cleanup(
    summary_service: SummaryService,
    session_manager: DatabaseSessionManager,
    published_events: list[Event],
) -> None:
    """Verify replacing handwrite_inner_name and purging expired soft-deleted summaries publish BlobCleanupEvent."""
    summary = await summary_service.add_summary(
        USER_EMAIL,
        AddSummaryDTO(
            unique_identifier="sum-hw-1",
            content="Summary with handwriting",
            handwrite_inner_name="hw-old.bin",
            handwrite_md5="md5-old",
        ),
    )
    group = await summary_service.add_group(
        USER_EMAIL,
        AddSummaryGroupDTO(
            unique_identifier="grp-hw-1",
            name="Group with handwriting",
            md5_hash="gh1",
        ),
    )
    assert summary.id is not None and group.id is not None

    await summary_service.update_group(
        USER_EMAIL,
        UpdateSummaryGroupDTO(
            id=group.id,
            unique_identifier="grp-hw-1",
            md5_hash="gh2",
            handwrite_inner_name="grp-hw-old.bin",
        ),
    )
    # Near-misses: updating with the same handwrite_inner_name or omitting it must not publish cleanup
    await summary_service.update_summary(
        USER_EMAIL,
        UpdateSummaryDTO(id=summary.id, handwrite_inner_name="hw-old.bin"),
    )
    await summary_service.update_summary(
        USER_EMAIL,
        UpdateSummaryDTO(id=summary.id, content="Edited text only"),
    )
    await summary_service.update_group(
        USER_EMAIL,
        UpdateSummaryGroupDTO(
            id=group.id,
            unique_identifier="grp-hw-1",
            md5_hash="gh2",
            handwrite_inner_name="grp-hw-old.bin",
        ),
    )
    await asyncio.sleep(0)
    assert published_events == []

    # Replacing handwrite_inner_name publishes BlobCleanupEvent for the old key
    await summary_service.update_summary(
        USER_EMAIL,
        UpdateSummaryDTO(
            id=summary.id,
            handwrite_inner_name="hw-new.bin",
            handwrite_md5="md5-new",
        ),
    )
    await summary_service.update_group(
        USER_EMAIL,
        UpdateSummaryGroupDTO(
            id=group.id,
            unique_identifier="grp-hw-1",
            md5_hash="gh3",
            handwrite_inner_name="grp-hw-new.bin",
        ),
    )
    await asyncio.sleep(0)
    assert published_events == [
        BlobCleanupEvent(storage_keys={"hw-old.bin"}),
        BlobCleanupEvent(storage_keys={"grp-hw-old.bin"}),
    ]
    published_events.clear()

    # Near-miss: an active summary older than the retention window must not be purged
    active_old = await summary_service.add_summary(
        USER_EMAIL,
        AddSummaryDTO(
            unique_identifier="sum-active-old",
            content="Old active summary",
            handwrite_inner_name="hw-active-old.bin",
        ),
    )
    assert active_old.id is not None

    # Soft-deleting does not immediately purge or publish blob cleanup
    await summary_service.delete_summary(USER_EMAIL, summary.id)
    await summary_service.delete_group(USER_EMAIL, group.id)
    await asyncio.sleep(0)
    assert published_events == []
    assert await summary_service.purge_expired_summaries() == 0

    # Set summary at exact cutoff, active_old older than cutoff, and group 1ms inside retention window
    cutoff_ms = int(time.time() * 1000) - RECYCLE_RETENTION_MS
    async with session_manager.session() as session:
        await session.execute(
            update(SummaryDO)
            .where(SummaryDO.id == summary.id)
            .values(update_time=cutoff_ms)
        )
        await session.execute(
            update(SummaryDO)
            .where(SummaryDO.id == active_old.id)
            .values(update_time=cutoff_ms - 10_000)
        )
        await session.execute(
            update(SummaryDO)
            .where(SummaryDO.id == group.id)
            .values(update_time=cutoff_ms + 1)
        )
        await session.commit()

    purged_count = await summary_service.purge_expired_summaries(
        older_than_ms=cutoff_ms
    )
    await asyncio.sleep(0)
    assert purged_count == 1
    assert published_events == [BlobCleanupEvent(storage_keys={"hw-new.bin"})]

    # Expired soft-deleted summary is hard-deleted; active old summary and 1ms-newer soft-deleted group row survive
    with pytest.raises(SummaryNotFound):
        await summary_service.get_summary(USER_EMAIL, summary.id)
    assert await summary_service.get_summary(USER_EMAIL, active_old.id) is not None
    with pytest.raises(SummaryNotFound):
        await summary_service.get_summary(USER_EMAIL, group.id)

    async with session_manager.session() as session:
        remaining_ids = set(
            (await session.execute(select(SummaryDO.id))).scalars().all()
        )
    assert remaining_ids == {active_old.id, group.id}


async def test_add_remove_and_readd_summary_and_group_lifecycle(
    summary_service: SummaryService,
    published_events: list[Event],
) -> None:
    """Verify adding, soft-deleting, and re-adding summaries and groups with the same unique_identifier."""
    group = await summary_service.add_group(
        USER_EMAIL,
        AddSummaryGroupDTO(
            unique_identifier="grp-lifecycle-1", name="Initial Group", md5_hash="gh-v1"
        ),
    )
    assert group.id is not None
    await summary_service.update_group(
        USER_EMAIL,
        UpdateSummaryGroupDTO(
            id=group.id,
            unique_identifier="grp-lifecycle-1",
            md5_hash="gh-v1",
            handwrite_inner_name="grp-hw-v1.bin",
        ),
    )
    child_1 = await summary_service.add_summary(
        USER_EMAIL,
        AddSummaryDTO(
            unique_identifier="sum-lifecycle-1",
            parent_unique_identifier="grp-lifecycle-1",
            content="Child 1 v1",
            handwrite_inner_name="sum-hw-v1.bin",
        ),
    )
    child_2 = await summary_service.add_summary(
        USER_EMAIL,
        AddSummaryDTO(
            unique_identifier="sum-lifecycle-2",
            parent_unique_identifier="grp-lifecycle-1",
            content="Child 2 v1",
            handwrite_inner_name="sum-2-hw-v1.bin",
        ),
    )
    assert child_1.id is not None and child_2.id is not None

    # Soft-delete the group (cascades soft-delete to child_1 and child_2)
    await summary_service.delete_group(USER_EMAIL, group.id)
    assert (
        await summary_service.get_summary_by_uuid(USER_EMAIL, "grp-lifecycle-1") is None
    )
    assert (
        await summary_service.get_summary_by_uuid(USER_EMAIL, "sum-lifecycle-1") is None
    )
    with pytest.raises(SummaryNotFound):
        await summary_service.get_summary(USER_EMAIL, child_1.id)
    with pytest.raises(SummaryNotFound):
        await summary_service.update_summary(
            USER_EMAIL, UpdateSummaryDTO(id=child_1.id, content="Should fail")
        )
    with pytest.raises(SummaryNotFound):
        await summary_service.delete_summary(USER_EMAIL, child_1.id)

    # Re-add group and children with the same unique_identifier -> replaces soft-deleted rows and cleans up superseded blobs
    revived_group = await summary_service.add_group(
        USER_EMAIL,
        AddSummaryGroupDTO(
            unique_identifier="grp-lifecycle-1", name="Revived Group", md5_hash="gh-v2"
        ),
    )
    assert revived_group.is_deleted == BooleanEnum.NO
    assert await summary_service.list_summaries(USER_EMAIL) == []

    revived_child_1 = await summary_service.add_summary(
        USER_EMAIL,
        AddSummaryDTO(
            unique_identifier="sum-lifecycle-1",
            parent_unique_identifier="grp-lifecycle-1",
            content="Child 1 revived same hw",
            handwrite_inner_name="sum-hw-v1.bin",
        ),
    )
    revived_child_2 = await summary_service.add_summary(
        USER_EMAIL,
        AddSummaryDTO(
            unique_identifier="sum-lifecycle-2",
            parent_unique_identifier="grp-lifecycle-1",
            content="Child 2 revived new hw",
            handwrite_inner_name="sum-2-hw-v2.bin",
        ),
    )
    await asyncio.sleep(0)
    assert published_events == [
        BlobCleanupEvent(storage_keys={"grp-hw-v1.bin"}),
        BlobCleanupEvent(storage_keys={"sum-2-hw-v1.bin"}),
    ]
    active_summaries = await summary_service.list_summaries(
        USER_EMAIL, parent_uuid="grp-lifecycle-1"
    )
    assert [s.id for s in active_summaries] == [revived_child_1.id, revived_child_2.id]
