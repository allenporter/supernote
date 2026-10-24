"""Unit tests for SummaryService."""

import hashlib
import math
from dataclasses import replace
from unittest.mock import patch

import pytest

from supernote.models.summary import (
    AddSummaryDTO,
    AddSummaryGroupDTO,
    QuerySummaryDTO,
    QuerySummaryGroupDTO,
    UpdateSummaryDTO,
    UpdateSummaryGroupDTO,
)
from supernote.models.user import UserRegisterDTO
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import SummaryNotFound
from supernote.server.services.blob import BlobStorage
from supernote.server.services.summary import SummaryService
from supernote.server.services.user import UserService

USER_EMAIL = "test@example.com"


@pytest.fixture
async def summary_service(
    user_service: UserService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> SummaryService:
    """Create a SummaryService bound to the test session manager with a registered test user."""
    await user_service.register(UserRegisterDTO(email=USER_EMAIL, password="a" * 32))
    return SummaryService(
        user_service=user_service,
        session_manager=session_manager,
        blob_storage=blob_storage,
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


async def test_delete_user_data_purges_summaries_tags_and_isolated_blobs(
    summary_service: SummaryService,
    user_service: UserService,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify delete_user_data deletes target user's records and exclusive blobs while preserving cross-tenant blobs."""
    other_email = "other@example.com"
    await user_service.register(UserRegisterDTO(email=other_email, password="b" * 32))
    u1_id = await user_service.get_user_id(USER_EMAIL)
    u2_id = await user_service.get_user_id(other_email)

    u1_exclusive_hw = "u1-exclusive-hw"
    shared_hw = "shared-summary-hw"
    u2_file_blob = "u2-file-storage-key"

    await blob_storage.put(USER_DATA_BUCKET, u1_exclusive_hw, b"u1-hw")
    await blob_storage.put(USER_DATA_BUCKET, shared_hw, b"shared-hw")
    await blob_storage.put(USER_DATA_BUCKET, u2_file_blob, b"u2-file")

    await summary_service.add_tag(USER_EMAIL, "U1 Tag")
    await summary_service.add_tag(other_email, "U2 Tag")

    await summary_service.add_summary(
        USER_EMAIL,
        AddSummaryDTO(
            unique_identifier="u1-s1",
            content="U1 exclusive",
            handwrite_inner_name=u1_exclusive_hw,
        ),
    )
    await summary_service.add_summary(
        USER_EMAIL,
        AddSummaryDTO(
            unique_identifier="u1-s2",
            content="U1 referencing shared hw",
            handwrite_inner_name=shared_hw,
        ),
    )
    await summary_service.add_summary(
        USER_EMAIL,
        AddSummaryDTO(
            unique_identifier="u1-s3",
            content="U1 referencing u2 file key",
            handwrite_inner_name=u2_file_blob,
        ),
    )
    await summary_service.add_summary(
        USER_EMAIL,
        AddSummaryDTO(
            unique_identifier="u1-s4",
            content="U1 malformed hw key",
            handwrite_inner_name="x",
        ),
    )
    await summary_service.add_summary(
        other_email,
        AddSummaryDTO(
            unique_identifier="u2-s1",
            content="U2 summary",
            handwrite_inner_name=shared_hw,
        ),
    )

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                user_id=u2_id,
                directory_id=0,
                file_name="u2.txt",
                is_folder="N",
                storage_key=u2_file_blob,
            )
        )
        await session.commit()

    # Transient OSError during blob deletion preserves DB metadata so retry finishes cleanup
    orig_delete = blob_storage.delete
    calls = 0

    async def flaky_delete(bucket: str, key: str) -> None:
        nonlocal calls
        calls += 1
        if key == u1_exclusive_hw and calls == 1:
            raise OSError("Simulated transient storage failure")
        await orig_delete(bucket, key)

    with (
        patch.object(blob_storage, "delete", side_effect=flaky_delete),
        pytest.raises(OSError, match="Simulated transient storage failure"),
    ):
        await summary_service.delete_user_data(u1_id)

    # Metadata is still intact after transient failure; retry completes idempotently
    assert len(await summary_service.list_summaries(USER_EMAIL)) == 4
    await summary_service.delete_user_data(u1_id)

    assert await summary_service.list_tags(USER_EMAIL) == []
    assert await summary_service.list_summaries(USER_EMAIL) == []
    assert len(await summary_service.list_tags(other_email)) == 1
    assert len(await summary_service.list_summaries(other_email)) == 1

    assert not await blob_storage.exists(USER_DATA_BUCKET, u1_exclusive_hw)
    assert await blob_storage.exists(USER_DATA_BUCKET, shared_hw)
    assert await blob_storage.exists(USER_DATA_BUCKET, u2_file_blob)
