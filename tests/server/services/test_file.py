"""Unit tests for FileService recycle bin purge, reference-counted blob cleanup, and event publishing."""

import asyncio
import hashlib
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select, update

from supernote.server.constants import (
    CACHE_BUCKET,
    RECYCLE_RETENTION_MS,
    USER_DATA_BUCKET,
)
from supernote.server.db.models.file import RecycleFileDO
from supernote.server.db.models.summary import SummaryDO
from supernote.server.db.models.user import FALLBACK_QUOTA, UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import (
    Event,
    LocalEventBus,
    NoteDeletedEvent,
    VfsItemCopiedEvent,
    VfsItemCreatedEvent,
    VfsItemDeletedEvent,
    VfsItemMovedEvent,
)
from supernote.server.exceptions import QuotaExceeded
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.user import UserService
from supernote.server.services.vfs import VirtualFileSystem
from supernote.server.utils.paths import get_conversion_pdf_path


@pytest.fixture
def event_bus() -> LocalEventBus:
    """Real LocalEventBus for verifying published domain events."""
    return LocalEventBus()


@pytest.fixture
def published_events(event_bus: LocalEventBus) -> list[Event]:
    """Capture domain events published on the LocalEventBus."""
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    event_bus.subscribe(NoteDeletedEvent, capture)
    return events


@pytest.fixture
def file_service(
    storage_root: Path,
    blob_storage: BlobStorage,
    user_service: UserService,
    session_manager: DatabaseSessionManager,
    event_bus: LocalEventBus,
) -> FileService:
    """Fixture providing FileService with explicit DI dependencies."""
    return FileService(
        storage_root=storage_root,
        blob_storage=blob_storage,
        user_service=user_service,
        session_manager=session_manager,
        event_bus=event_bus,
    )


async def test_recycle_bin_lifecycle(
    file_service: FileService,
    blob_storage: BlobStorage,
    published_events: list[Event],
    test_user_id: int,
    test_users: list[str],
) -> None:
    """Verify moving files to recycle bin, restoring, permanent deletion, and NoteDeletedEvent."""
    user = test_users[0]
    content = b"recycle bin test note"
    md5 = hashlib.md5(content).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "rec_blob", content)
    file_entity = await file_service.finish_upload(
        user, "rec_item.note", "/", md5, "rec_blob"
    )

    # Soft delete (move to recycle bin)
    await file_service.delete_item(user, file_entity.id)
    root_items = await file_service.list_folder(user, "/")
    assert not any(item.id == file_entity.id for item in root_items)

    recycled_items = await file_service.list_recycle(user)
    assert len(recycled_items) == 1
    assert recycled_items[0].name == "rec_item.note"
    recycle_id = recycled_items[0].id

    # Revert from recycle bin
    await file_service.revert_from_recycle(user, [recycle_id])
    assert len(await file_service.list_recycle(user)) == 0
    restored_items = await file_service.list_folder(user, "/")
    assert any(item.id == file_entity.id for item in restored_items)

    # Delete again and permanently purge
    await file_service.delete_item(user, file_entity.id)
    recycled_items_2 = await file_service.list_recycle(user)
    recycle_id_2 = recycled_items_2[0].id

    published_events.clear()
    await file_service.delete_from_recycle(user, [recycle_id_2])
    await asyncio.sleep(0)
    assert len(await file_service.list_recycle(user)) == 0
    assert await blob_storage.exists(USER_DATA_BUCKET, "rec_blob") is False

    # Permanent purge of .note publishes NoteDeletedEvent
    assert published_events == [
        NoteDeletedEvent(file_id=file_entity.id, user_id=test_user_id)
    ]


async def test_file_shared_blob_reference_counting(
    file_service: FileService,
    blob_storage: BlobStorage,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Verify blob survives until all copies referencing its storage key are permanently purged."""
    user = test_users[0]
    content = b"shared content bytes"
    md5 = hashlib.md5(content).hexdigest()
    storage_key = "shared_key_1"
    await blob_storage.put(USER_DATA_BUCKET, storage_key, content)

    orig_file = await file_service.finish_upload(
        user, "orig.txt", "/", md5, storage_key
    )
    copied_file = await file_service.copy_item(
        user, orig_file.id, to_path="/copy.txt", autorename=True
    )
    assert copied_file.storage_key == orig_file.storage_key

    # Soft-delete and permanently purge original file
    await file_service.delete_item(user, orig_file.id)
    recycle_orig = (await file_service.list_recycle(user))[0]
    await file_service.delete_from_recycle(user, [recycle_orig.id])

    # Physical blob survives because copy still references it
    assert await blob_storage.exists(USER_DATA_BUCKET, storage_key) is True

    # Soft-delete and permanently purge copy
    await file_service.delete_item(user, copied_file.id)
    recycle_copy = (await file_service.list_recycle(user))[0]
    await file_service.delete_from_recycle(user, [recycle_copy.id])

    # Physical blob is deleted now that no references survive
    assert await blob_storage.exists(USER_DATA_BUCKET, storage_key) is False


async def test_file_purge_multiple_files_shared_blob_single_deletion(
    file_service: FileService,
    blob_storage: BlobStorage,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Verify permanently purging multiple files sharing the same blob key executes a single blob deletion."""
    user = test_users[0]
    content = b"shared content bytes 2"
    md5 = hashlib.md5(content).hexdigest()
    storage_key = "shared_key_2"
    await blob_storage.put(USER_DATA_BUCKET, storage_key, content)

    f1 = await file_service.finish_upload(user, "f1.txt", "/", md5, storage_key)
    f2 = await file_service.copy_item(user, f1.id, to_path="/f2.txt", autorename=True)
    f3 = await file_service.copy_item(user, f1.id, to_path="/f3.txt", autorename=True)

    await file_service.delete_item(user, f1.id)
    await file_service.delete_item(user, f2.id)
    await file_service.delete_item(user, f3.id)

    recycle_ids = [r.id for r in await file_service.list_recycle(user)]
    assert len(recycle_ids) == 3

    delete_calls: list[tuple[str, str]] = []
    orig_delete = blob_storage.delete

    async def tracking_delete(bucket: str, key: str) -> None:
        delete_calls.append((bucket, key))
        await orig_delete(bucket, key)

    setattr(blob_storage, "delete", tracking_delete)

    await file_service.delete_from_recycle(user, recycle_ids)

    matching_calls = [
        call for call in delete_calls if call == (USER_DATA_BUCKET, storage_key)
    ]
    assert len(matching_calls) == 1
    assert await blob_storage.exists(USER_DATA_BUCKET, storage_key) is False


async def test_recycle_bin_opportunistic_retention_cleanup(
    file_service: FileService,
    blob_storage: BlobStorage,
    session_manager: DatabaseSessionManager,
    published_events: list[Event],
    test_user_id: int,
    test_users: list[str],
) -> None:
    """Verify expired recycle bin items (>30 days) are opportunistically purged while recent items survive."""
    user = test_users[0]
    content = b"expired note content"
    md5 = hashlib.md5(content).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "expired_blob", content)
    await blob_storage.put(USER_DATA_BUCKET, "recent_blob", content)

    expired_file = await file_service.finish_upload(
        user, "expired.note", "/", md5, "expired_blob"
    )
    recent_file = await file_service.finish_upload(
        user, "recent.note", "/", md5, "recent_blob"
    )

    await file_service.delete_item(user, expired_file.id)
    await file_service.delete_item(user, recent_file.id)

    # Backdate expired_file's delete_time beyond the 30-day retention window
    expired_time = int(time.time() * 1000) - RECYCLE_RETENTION_MS - 10_000
    async with session_manager.session() as session:
        await session.execute(
            update(RecycleFileDO)
            .where(RecycleFileDO.file_id == expired_file.id)
            .values(delete_time=expired_time)
        )
        await session.commit()

    published_events.clear()

    # Listing recycle bin opportunistically prunes the expired entry
    recycled = await file_service.list_recycle(user)
    await asyncio.sleep(0)
    assert [r.name for r in recycled] == ["recent.note"]
    assert await blob_storage.exists(USER_DATA_BUCKET, "expired_blob") is False
    assert await blob_storage.exists(USER_DATA_BUCKET, "recent_blob") is True

    assert published_events == [
        NoteDeletedEvent(file_id=expired_file.id, user_id=test_user_id)
    ]


async def test_finish_upload_overwrite_deletes_superseded_blob(
    file_service: FileService,
    blob_storage: BlobStorage,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Overwriting an existing file via device finish_upload deletes the superseded storage_key blob."""
    user = test_users[0]
    content_v1 = b"version 1 content"
    md5_v1 = hashlib.md5(content_v1).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "blob_v1_key", content_v1)

    entity_v1 = await file_service.finish_upload(
        user, "overwrite.note", "/", md5_v1, "blob_v1_key"
    )
    assert await blob_storage.exists(USER_DATA_BUCKET, "blob_v1_key") is True

    content_v2 = b"version 2 updated content"
    md5_v2 = hashlib.md5(content_v2).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "blob_v2_key", content_v2)

    entity_v2 = await file_service.finish_upload(
        user, "overwrite.note", "/", md5_v2, "blob_v2_key"
    )
    assert entity_v2.id == entity_v1.id
    assert entity_v2.storage_key == "blob_v2_key"
    assert await blob_storage.exists(USER_DATA_BUCKET, "blob_v1_key") is False
    assert await blob_storage.exists(USER_DATA_BUCKET, "blob_v2_key") is True


async def test_upload_finish_web_overwrite_deletes_superseded_blob(
    file_service: FileService,
    blob_storage: BlobStorage,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Overwriting an existing file via Web upload_finish_web deletes the superseded storage_key blob."""
    user = test_users[0]
    content_v1 = b"web version 1 content"
    md5_v1 = hashlib.md5(content_v1).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "web_blob_v1", content_v1)

    await file_service.upload_finish_web(
        user=user,
        directory_id=0,
        file_name="web_overwrite.note",
        md5=md5_v1,
        inner_name="web_blob_v1",
    )
    assert await blob_storage.exists(USER_DATA_BUCKET, "web_blob_v1") is True

    content_v2 = b"web version 2 content"
    md5_v2 = hashlib.md5(content_v2).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "web_blob_v2", content_v2)

    await file_service.upload_finish_web(
        user=user,
        directory_id=0,
        file_name="web_overwrite.note",
        md5=md5_v2,
        inner_name="web_blob_v2",
    )
    assert await blob_storage.exists(USER_DATA_BUCKET, "web_blob_v1") is False
    assert await blob_storage.exists(USER_DATA_BUCKET, "web_blob_v2") is True


async def test_overwrite_copied_file_preserves_shared_blob(
    file_service: FileService,
    blob_storage: BlobStorage,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """If a copied file shares old_storage_key, overwriting one copy preserves the shared blob."""
    user = test_users[0]
    content_v1 = b"shared initial content"
    md5_v1 = hashlib.md5(content_v1).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "shared_v1_key", content_v1)

    orig_file = await file_service.finish_upload(
        user, "orig_copy.note", "/", md5_v1, "shared_v1_key"
    )
    copied_file = await file_service.copy_item(
        user, orig_file.id, to_path="/copied.note", autorename=True
    )
    assert copied_file.storage_key == "shared_v1_key"

    # Overwrite original file with v2
    content_v2 = b"updated original content"
    md5_v2 = hashlib.md5(content_v2).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "orig_v2_key", content_v2)

    await file_service.finish_upload(user, "orig_copy.note", "/", md5_v2, "orig_v2_key")

    # Shared v1 blob must still exist because copied.note still references it
    assert await blob_storage.exists(USER_DATA_BUCKET, "shared_v1_key") is True
    assert await blob_storage.exists(USER_DATA_BUCKET, "orig_v2_key") is True

    # Overwrite the copy as well -> now no row references shared_v1_key
    content_v3 = b"updated copy content"
    md5_v3 = hashlib.md5(content_v3).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "copy_v3_key", content_v3)

    await file_service.finish_upload(user, "copied.note", "/", md5_v3, "copy_v3_key")
    assert await blob_storage.exists(USER_DATA_BUCKET, "shared_v1_key") is False
    assert await blob_storage.exists(USER_DATA_BUCKET, "copy_v3_key") is True


async def test_overwrite_file_cleans_up_stale_conversion_blobs(
    file_service: FileService,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_users: list[str],
) -> None:
    """Stale conversions/ PDF blob from the previous file MD5 is cleaned up upon overwrite."""
    user = test_users[0]
    content_v1 = b"note content v1"
    md5_v1 = hashlib.md5(content_v1).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "conv_blob_v1", content_v1)

    entity_v1 = await file_service.finish_upload(
        user, "converted.note", "/", md5_v1, "conv_blob_v1"
    )

    pdf_v1 = get_conversion_pdf_path(
        user_id=test_user_id, file_id=entity_v1.id, file_md5=md5_v1
    )
    await blob_storage.put(CACHE_BUCKET, pdf_v1, b"pdf bytes")
    assert await blob_storage.exists(CACHE_BUCKET, pdf_v1) is True

    # Overwrite with v2 (different MD5)
    content_v2 = b"note content v2"
    md5_v2 = hashlib.md5(content_v2).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "conv_blob_v2", content_v2)

    await file_service.finish_upload(
        user, "converted.note", "/", md5_v2, "conv_blob_v2"
    )

    assert await blob_storage.exists(CACHE_BUCKET, pdf_v1) is False


async def test_overwrite_same_md5_deletes_superseded_blob_but_preserves_conversions(
    file_service: FileService,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_users: list[str],
) -> None:
    """Re-uploading a file with identical MD5 deletes old storage_key but keeps valid conversion blobs."""
    user = test_users[0]
    content = b"identical note content"
    md5 = hashlib.md5(content).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "same_md5_blob_1", content)

    entity = await file_service.finish_upload(
        user, "same_md5.note", "/", md5, "same_md5_blob_1"
    )

    pdf_key = get_conversion_pdf_path(
        user_id=test_user_id, file_id=entity.id, file_md5=md5
    )
    await blob_storage.put(CACHE_BUCKET, pdf_key, b"pdf")

    await blob_storage.put(USER_DATA_BUCKET, "same_md5_blob_2", content)
    await file_service.finish_upload(user, "same_md5.note", "/", md5, "same_md5_blob_2")

    assert await blob_storage.exists(USER_DATA_BUCKET, "same_md5_blob_1") is False
    assert await blob_storage.exists(USER_DATA_BUCKET, "same_md5_blob_2") is True
    assert await blob_storage.exists(CACHE_BUCKET, pdf_key) is True


async def test_overwrite_file_with_soft_deleted_copy_in_recycle_preserves_shared_blob(
    file_service: FileService,
    blob_storage: BlobStorage,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Overwriting a file when a copy is soft-deleted in the recycle bin preserves the shared blob."""
    user = test_users[0]
    content_v1 = b"shared with recycle bin copy"
    md5_v1 = hashlib.md5(content_v1).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "shared_recycle_key", content_v1)

    orig_file = await file_service.finish_upload(
        user, "active_orig.note", "/", md5_v1, "shared_recycle_key"
    )
    trashed_copy = await file_service.copy_item(
        user, orig_file.id, to_path="/trashed_copy.note", autorename=True
    )
    await file_service.delete_item(user, trashed_copy.id)

    # Overwrite active_orig.note with v2 while trashed_copy is in the recycle bin
    content_v2 = b"updated active orig"
    md5_v2 = hashlib.md5(content_v2).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "active_orig_v2", content_v2)
    await file_service.finish_upload(
        user, "active_orig.note", "/", md5_v2, "active_orig_v2"
    )

    # Shared v1 blob must survive so trashed_copy can still be restored from recycle bin
    assert await blob_storage.exists(USER_DATA_BUCKET, "shared_recycle_key") is True


async def test_purge_recycle_cleans_up_conversion_blobs(
    file_service: FileService,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_users: list[str],
) -> None:
    """Permanently purging a file from the recycle bin also deletes its cached conversion blobs."""
    user = test_users[0]
    content = b"note with conversions to purge"
    md5 = hashlib.md5(content).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "purge_conv_blob", content)

    entity = await file_service.finish_upload(
        user, "purge_conv.note", "/", md5, "purge_conv_blob"
    )
    pdf_key = get_conversion_pdf_path(
        user_id=test_user_id, file_id=entity.id, file_md5=md5
    )
    await blob_storage.put(CACHE_BUCKET, pdf_key, b"pdf")

    await file_service.delete_item(user, entity.id)
    recycled = await file_service.list_recycle(user)
    await file_service.delete_from_recycle(user, [recycled[0].id])

    assert await blob_storage.exists(USER_DATA_BUCKET, "purge_conv_blob") is False
    assert await blob_storage.exists(CACHE_BUCKET, pdf_key) is False


async def test_query_file_list_and_get_folders_by_ids_resolve_parent_path_once(
    file_service: FileService,
    blob_storage: BlobStorage,
    create_test_user: None,
    test_users: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify query_file_list and get_folders_by_ids resolve parent path once instead of per child item."""
    user = test_users[0]
    parent_dir = await file_service.create_directory(user, "/Note/Projects")
    sub_a = await file_service.create_directory(user, "/Note/Projects/Alpha")
    sub_b = await file_service.create_directory(user, "/Note/Projects/Beta")
    await file_service.create_directory(user, "/Note/Projects/Alpha/Nested")

    content = b"project note"
    md5 = hashlib.md5(content).hexdigest()
    for idx in range(3):
        key = f"proj_blob_{idx}"
        await blob_storage.put(USER_DATA_BUCKET, key, content)
        await file_service.finish_upload(
            user, f"doc_{idx}.note", "/Note/Projects", md5, key
        )

    orig_get_full_path = VirtualFileSystem.get_full_path
    get_full_path_calls: list[int] = []

    async def tracking_get_full_path(
        self: VirtualFileSystem, user_id: int, node_id: int
    ) -> str:
        get_full_path_calls.append(node_id)
        return await orig_get_full_path(self, user_id, node_id)

    monkeypatch.setattr(VirtualFileSystem, "get_full_path", tracking_get_full_path)

    # query_file_list resolves parent_dir.id once for all 5 children (2 folders + 3 files)
    items = await file_service.query_file_list(user, parent_dir.id)
    assert len(items) == 5
    assert get_full_path_calls == [parent_dir.id]
    assert {item.full_path for item in items} == {
        "NOTE/Note/Projects/Alpha",
        "NOTE/Note/Projects/Beta",
        "NOTE/Note/Projects/doc_0.note",
        "NOTE/Note/Projects/doc_1.note",
        "NOTE/Note/Projects/doc_2.note",
    }

    # get_folders_by_ids resolves parent_dir.id once for all non-excluded folders
    get_full_path_calls.clear()
    folder_details = await file_service.get_folders_by_ids(
        user, parent_id=parent_dir.id, id_list=[]
    )
    assert len(folder_details) == 2
    assert get_full_path_calls == [parent_dir.id]
    by_id = {fd.entity.id: fd for fd in folder_details}
    assert by_id[sub_a.id].entity.full_path == "NOTE/Note/Projects/Alpha"
    assert by_id[sub_a.id].has_subfolders is True
    assert by_id[sub_b.id].entity.full_path == "NOTE/Note/Projects/Beta"
    assert by_id[sub_b.id].has_subfolders is False


async def test_search_files_caches_parent_paths(
    file_service: FileService,
    blob_storage: BlobStorage,
    create_test_user: None,
    test_users: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify search_files memoizes parent directory paths across multiple matching items."""
    user = test_users[0]
    folder = await file_service.create_directory(user, "/Note/Archive")
    content = b"searchable note"
    md5 = hashlib.md5(content).hexdigest()

    for idx in range(3):
        key = f"search_blob_{idx}"
        await blob_storage.put(USER_DATA_BUCKET, key, content)
        await file_service.finish_upload(
            user, f"match_{idx}.note", "/Note/Archive", md5, key
        )
    await blob_storage.put(USER_DATA_BUCKET, "root_search_blob", content)
    await file_service.finish_upload(
        user, "match_root.note", "/", md5, "root_search_blob"
    )

    orig_get_full_path = VirtualFileSystem.get_full_path
    get_full_path_calls: list[int] = []

    async def tracking_get_full_path(
        self: VirtualFileSystem, user_id: int, node_id: int
    ) -> str:
        get_full_path_calls.append(node_id)
        return await orig_get_full_path(self, user_id, node_id)

    monkeypatch.setattr(VirtualFileSystem, "get_full_path", tracking_get_full_path)

    results = await file_service.search_files(user, "match_")
    assert len(results) == 4
    # Root directory (0) is pre-seeded, and folder.id is resolved only once for all 3 matches in /Note/Archive
    assert get_full_path_calls == [folder.id]
    assert {item.full_path for item in results} == {
        "match_root.note",
        "NOTE/Note/Archive/match_0.note",
        "NOTE/Note/Archive/match_1.note",
        "NOTE/Note/Archive/match_2.note",
    }


async def test_file_service_publishes_vfs_domain_events(
    file_service: FileService,
    blob_storage: BlobStorage,
    event_bus: LocalEventBus,
    test_user_id: int,
    test_users: list[str],
) -> None:
    """Verify FileService emits VfsItemCreatedEvent, VfsItemMovedEvent, VfsItemCopiedEvent, and VfsItemDeletedEvent."""
    user = test_users[0]
    vfs_events: list[Event] = []

    async def on_vfs_event(event: Event) -> None:
        vfs_events.append(event)

    event_bus.subscribe(VfsItemCreatedEvent, on_vfs_event)
    event_bus.subscribe(VfsItemMovedEvent, on_vfs_event)
    event_bus.subscribe(VfsItemCopiedEvent, on_vfs_event)
    event_bus.subscribe(VfsItemDeletedEvent, on_vfs_event)

    dir_a = await file_service.create_directory(user, "/WorkDir")
    await asyncio.sleep(0)
    assert vfs_events == [
        VfsItemCreatedEvent(
            user_id=test_user_id,
            item_id=dir_a.id,
            parent_id=0,
            name="WorkDir",
            is_folder=True,
            full_path="WorkDir",
        )
    ]
    vfs_events.clear()

    # Calling create_directory or create_directory_by_id on an existing directory is a no-op
    await file_service.create_directory(user, "/WorkDir")
    await file_service.create_directory_by_id(user, 0, "WorkDir")
    await asyncio.sleep(0)
    assert vfs_events == []

    dir_b = await file_service.create_directory_by_id(user, dir_a.id, "SubDir")
    await asyncio.sleep(0)
    assert vfs_events == [
        VfsItemCreatedEvent(
            user_id=test_user_id,
            item_id=dir_b.id,
            parent_id=dir_a.id,
            name="SubDir",
            is_folder=True,
            full_path="WorkDir/SubDir",
        )
    ]
    vfs_events.clear()

    content = b"vfs event payload"
    md5 = hashlib.md5(content).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "vfs_blob_1", content)
    file_1 = await file_service.finish_upload(
        user, "doc1.pdf", "/WorkDir", md5, "vfs_blob_1"
    )
    await asyncio.sleep(0)
    assert vfs_events == [
        VfsItemCreatedEvent(
            user_id=test_user_id,
            item_id=file_1.id,
            parent_id=dir_a.id,
            name="doc1.pdf",
            is_folder=False,
            full_path="WorkDir/doc1.pdf",
            size=len(content),
            md5=md5,
        )
    ]
    vfs_events.clear()

    await blob_storage.put(USER_DATA_BUCKET, "vfs_blob_2", content)
    await file_service.upload_finish_web(
        user=user,
        directory_id=dir_a.id,
        file_name="web_doc.pdf",
        md5=md5,
        inner_name="vfs_blob_2",
    )
    web_file = await file_service.get_file_info(user, "/WorkDir/web_doc.pdf")
    assert web_file is not None
    await asyncio.sleep(0)
    assert vfs_events == [
        VfsItemCreatedEvent(
            user_id=test_user_id,
            item_id=web_file.id,
            parent_id=dir_a.id,
            name="web_doc.pdf",
            is_folder=False,
            full_path="WorkDir/web_doc.pdf",
            size=len(content),
            md5=md5,
        )
    ]
    vfs_events.clear()

    await file_service.rename_item(user, file_1.id, "doc1_renamed.pdf")
    await asyncio.sleep(0)
    assert vfs_events == [
        VfsItemMovedEvent(
            user_id=test_user_id,
            item_id=file_1.id,
            original_parent_id=dir_a.id,
            new_parent_id=dir_a.id,
            original_name="doc1.pdf",
            new_name="doc1_renamed.pdf",
            original_full_path="WorkDir/doc1.pdf",
            new_full_path="WorkDir/doc1_renamed.pdf",
            is_folder=False,
            size=len(content),
            md5=md5,
        )
    ]
    vfs_events.clear()

    # Identity move to same path is a no-op and emits no event
    await file_service.move_item(
        user, file_1.id, "/WorkDir/doc1_renamed.pdf", autorename=False
    )
    await asyncio.sleep(0)
    assert vfs_events == []

    await file_service.move_item(
        user, file_1.id, "/WorkDir/SubDir/doc1_moved.pdf", autorename=False
    )
    await asyncio.sleep(0)
    assert vfs_events == [
        VfsItemMovedEvent(
            user_id=test_user_id,
            item_id=file_1.id,
            original_parent_id=dir_a.id,
            new_parent_id=dir_b.id,
            original_name="doc1_renamed.pdf",
            new_name="doc1_moved.pdf",
            original_full_path="WorkDir/doc1_renamed.pdf",
            new_full_path="WorkDir/SubDir/doc1_moved.pdf",
            is_folder=False,
            size=len(content),
            md5=md5,
        )
    ]
    vfs_events.clear()

    await file_service.move_items(user, [web_file.id], target_parent_id=dir_b.id)
    await asyncio.sleep(0)
    assert vfs_events == [
        VfsItemMovedEvent(
            user_id=test_user_id,
            item_id=web_file.id,
            original_parent_id=dir_a.id,
            new_parent_id=dir_b.id,
            original_name="web_doc.pdf",
            new_name="web_doc.pdf",
            original_full_path="WorkDir/web_doc.pdf",
            new_full_path="WorkDir/SubDir/web_doc.pdf",
            is_folder=False,
            size=len(content),
            md5=md5,
        )
    ]
    vfs_events.clear()

    copied = await file_service.copy_item(
        user, file_1.id, to_path="/WorkDir/doc1_copy.pdf", autorename=True
    )
    await asyncio.sleep(0)
    assert vfs_events == [
        VfsItemCopiedEvent(
            user_id=test_user_id,
            source_id=file_1.id,
            new_id=copied.id,
            source_parent_id=dir_b.id,
            new_parent_id=dir_a.id,
            original_name="doc1_moved.pdf",
            new_name="doc1_copy.pdf",
            original_full_path="WorkDir/SubDir/doc1_moved.pdf",
            new_full_path="WorkDir/doc1_copy.pdf",
            is_folder=False,
            size=len(content),
            md5=md5,
        )
    ]
    vfs_events.clear()

    await file_service.copy_items(user, [web_file.id], target_parent_id=dir_a.id)
    web_copied = await file_service.get_file_info(user, "/WorkDir/web_doc.pdf")
    assert web_copied is not None
    await asyncio.sleep(0)
    assert vfs_events == [
        VfsItemCopiedEvent(
            user_id=test_user_id,
            source_id=web_file.id,
            new_id=web_copied.id,
            source_parent_id=dir_b.id,
            new_parent_id=dir_a.id,
            original_name="web_doc.pdf",
            new_name="web_doc.pdf",
            original_full_path="WorkDir/SubDir/web_doc.pdf",
            new_full_path="WorkDir/web_doc.pdf",
            is_folder=False,
            size=len(content),
            md5=md5,
        )
    ]
    vfs_events.clear()

    await file_service.delete_item(user, copied.id)
    await asyncio.sleep(0)
    assert vfs_events == [
        VfsItemDeletedEvent(
            user_id=test_user_id,
            item_id=copied.id,
            parent_id=dir_a.id,
            name="doc1_copy.pdf",
            full_path="WorkDir/doc1_copy.pdf",
            is_folder=False,
            size=len(content),
            md5=md5,
        )
    ]
    vfs_events.clear()

    await file_service.delete_items(user, [web_copied.id], parent_id=dir_a.id)
    await asyncio.sleep(0)
    assert vfs_events == [
        VfsItemDeletedEvent(
            user_id=test_user_id,
            item_id=web_copied.id,
            parent_id=dir_a.id,
            name="web_doc.pdf",
            full_path="WorkDir/web_doc.pdf",
            is_folder=False,
            size=len(content),
            md5=md5,
        )
    ]
    vfs_events.clear()

    recycle_entries = await file_service.list_recycle(user)
    copied_recycle = next(r for r in recycle_entries if r.name == "doc1_copy.pdf")
    await file_service.revert_from_recycle(user, [copied_recycle.id])
    await asyncio.sleep(0)
    assert vfs_events == [
        VfsItemCreatedEvent(
            user_id=test_user_id,
            item_id=copied.id,
            parent_id=dir_a.id,
            name="doc1_copy.pdf",
            is_folder=False,
            full_path="WorkDir/doc1_copy.pdf",
            size=len(content),
            md5=md5,
        )
    ]


async def test_file_overwrite_and_purge_preserve_summary_referenced_blob(
    file_service: FileService,
    blob_storage: BlobStorage,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
    test_users: list[str],
) -> None:
    """Near-miss: overwriting or purging a file must not delete a blob still referenced by SummaryDO."""
    user = test_users[0]
    content_v1 = b"shared with summary v1"
    md5_v1 = hashlib.md5(content_v1).hexdigest()
    content_v2 = b"shared with summary v2"
    md5_v2 = hashlib.md5(content_v2).hexdigest()

    await blob_storage.put(USER_DATA_BUCKET, "shared_sum_key_v1", content_v1)
    await blob_storage.put(USER_DATA_BUCKET, "shared_sum_key_v2", content_v2)

    async with session_manager.session() as session:
        session.add_all(
            [
                SummaryDO(
                    user_id=test_user_id,
                    unique_identifier="sum-ref-v1",
                    handwrite_inner_name="shared_sum_key_v1",
                ),
                SummaryDO(
                    user_id=test_user_id,
                    unique_identifier="sum-ref-v2",
                    handwrite_inner_name="shared_sum_key_v2",
                ),
            ]
        )
        await session.commit()

    await file_service.finish_upload(
        user, "cross_ref.txt", "/", md5_v1, "shared_sum_key_v1"
    )
    # Overwrite with v2 -> v1 blob must survive because SummaryDO still references it
    entity_v2 = await file_service.finish_upload(
        user, "cross_ref.txt", "/", md5_v2, "shared_sum_key_v2"
    )
    assert await blob_storage.exists(USER_DATA_BUCKET, "shared_sum_key_v1") is True

    # Soft-delete and purge v2 -> v2 blob must survive because SummaryDO still references it
    await file_service.delete_item(user, entity_v2.id)
    recycled = await file_service.list_recycle(user)
    await file_service.delete_from_recycle(user, [recycled[0].id])
    assert await blob_storage.exists(USER_DATA_BUCKET, "shared_sum_key_v2") is True

    # Once SummaryDO rows are removed, cleanup_unreferenced_blobs deletes both keys
    async with session_manager.session() as session:
        await session.execute(
            delete(SummaryDO).where(SummaryDO.user_id == test_user_id)
        )
        await session.commit()

    await file_service.cleanup_unreferenced_blobs(
        {"shared_sum_key_v1", "shared_sum_key_v2"}
    )
    assert await blob_storage.exists(USER_DATA_BUCKET, "shared_sum_key_v1") is False
    assert await blob_storage.exists(USER_DATA_BUCKET, "shared_sum_key_v2") is False


async def test_get_storage_quota(
    file_service: FileService,
    blob_storage: BlobStorage,
    session_manager: DatabaseSessionManager,
    create_test_user: None,
    test_users: list[str],
    test_user_id: int,
) -> None:
    """Verify two-tier quota resolution across volume free space, default_user_quota, and per-user overrides."""
    user = test_users[0]

    with patch.object(blob_storage, "get_available_bytes", return_value=123456):
        assert await file_service.get_storage_quota(user) == 123456

    with patch.object(blob_storage, "get_available_bytes", return_value=None):
        assert await file_service.get_storage_quota(user) == FALLBACK_QUOTA

    file_service.default_user_quota = 10 * 1024 * 1024
    assert await file_service.get_storage_quota(user) == 10 * 1024 * 1024

    custom_quota = 50 * 1024 * 1024
    async with session_manager.session() as session:
        user_row = (
            await session.execute(select(UserDO).where(UserDO.id == test_user_id))
        ).scalar_one()
        user_row.total_capacity = str(custom_quota)
        await session.commit()

    assert await file_service.get_storage_quota(user) == custom_quota

    # Invalid stored quota string defers to server default_user_quota (or volume space when 0)
    async with session_manager.session() as session:
        user_row = (
            await session.execute(select(UserDO).where(UserDO.id == test_user_id))
        ).scalar_one()
        user_row.total_capacity = "not-an-int"
        await session.commit()

    assert await file_service.get_storage_quota(user) == 10 * 1024 * 1024
    file_service.default_user_quota = 0
    with patch.object(blob_storage, "get_available_bytes", return_value=99999):
        assert await file_service.get_storage_quota(user) == 99999


async def test_finish_upload_enforces_quota_and_purges_staged_blob(
    file_service: FileService,
    blob_storage: BlobStorage,
    session_manager: DatabaseSessionManager,
    create_test_user: None,
    test_users: list[str],
    test_user_id: int,
) -> None:
    """Verify device finish_upload deletes staged unreferenced blob and raises QuotaExceeded when over quota."""
    user = test_users[0]

    # Set quota to 500 bytes
    async with session_manager.session() as session:
        user_row = (
            await session.execute(select(UserDO).where(UserDO.id == test_user_id))
        ).scalar_one()
        user_row.total_capacity = "500"
        await session.commit()

    # Upload 300 bytes -> fits in 500 byte quota
    content1 = b"1" * 300
    md5_1 = hashlib.md5(content1).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "staged_blob_1", content1)

    entity1 = await file_service.finish_upload(
        user, "file1.txt", "/", md5_1, "staged_blob_1"
    )
    assert entity1.size == 300
    assert await blob_storage.exists(USER_DATA_BUCKET, "staged_blob_1") is True
    assert await file_service.get_storage_usage(user) == 300

    # Upload second file of 300 bytes -> total 600 > 500 -> QuotaExceeded
    content2 = b"2" * 300
    md5_2 = hashlib.md5(content2).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "staged_blob_overflow", content2)
    assert await blob_storage.exists(USER_DATA_BUCKET, "staged_blob_overflow") is True

    with pytest.raises(QuotaExceeded):
        await file_service.finish_upload(
            user, "file2.txt", "/", md5_2, "staged_blob_overflow"
        )

    # Staged blob must be deleted because upload was aborted
    assert await blob_storage.exists(USER_DATA_BUCKET, "staged_blob_overflow") is False
    # Usage must remain unchanged at 300
    assert await file_service.get_storage_usage(user) == 300


async def test_finish_upload_overwrite_accounts_for_net_size_change(
    file_service: FileService,
    blob_storage: BlobStorage,
    session_manager: DatabaseSessionManager,
    create_test_user: None,
    test_users: list[str],
    test_user_id: int,
) -> None:
    """Verify finish_upload calculates net_change when overwriting an active file."""
    user = test_users[0]

    # Set quota to 500 bytes
    async with session_manager.session() as session:
        user_row = (
            await session.execute(select(UserDO).where(UserDO.id == test_user_id))
        ).scalar_one()
        user_row.total_capacity = "500"
        await session.commit()

    # Upload original 400 bytes
    content_orig = b"a" * 400
    md5_orig = hashlib.md5(content_orig).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "blob_orig", content_orig)
    await file_service.finish_upload(
        user, "overwrite_test.txt", "/", md5_orig, "blob_orig"
    )
    assert await file_service.get_storage_usage(user) == 400

    # Overwrite with 450 bytes -> net change is +50 bytes (total 450 <= 500) -> succeeds!
    content_ok = b"b" * 450
    md5_ok = hashlib.md5(content_ok).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "blob_ok", content_ok)
    entity_ok = await file_service.finish_upload(
        user, "overwrite_test.txt", "/", md5_ok, "blob_ok"
    )
    assert entity_ok.size == 450
    assert await file_service.get_storage_usage(user) == 450
    assert await blob_storage.exists(USER_DATA_BUCKET, "blob_orig") is False
    assert await blob_storage.exists(USER_DATA_BUCKET, "blob_ok") is True

    # Overwrite with 600 bytes -> net change is +150 bytes (total 600 > 500) -> QuotaExceeded
    content_overflow = b"c" * 600
    md5_overflow = hashlib.md5(content_overflow).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "blob_overflow", content_overflow)
    with pytest.raises(QuotaExceeded):
        await file_service.finish_upload(
            user, "overwrite_test.txt", "/", md5_overflow, "blob_overflow"
        )

    # Staged overflow blob deleted; existing 450-byte file remains intact
    assert await blob_storage.exists(USER_DATA_BUCKET, "blob_overflow") is False
    assert await blob_storage.exists(USER_DATA_BUCKET, "blob_ok") is True
    assert await file_service.get_storage_usage(user) == 450


async def test_upload_finish_web_enforces_quota_and_purges_staged_blob(
    file_service: FileService,
    blob_storage: BlobStorage,
    session_manager: DatabaseSessionManager,
    create_test_user: None,
    test_users: list[str],
    test_user_id: int,
) -> None:
    """Verify Web upload_finish_web deletes staged unreferenced blob and raises QuotaExceeded when over quota."""
    user = test_users[0]

    # Set quota to 500 bytes
    async with session_manager.session() as session:
        user_row = (
            await session.execute(select(UserDO).where(UserDO.id == test_user_id))
        ).scalar_one()
        user_row.total_capacity = "500"
        await session.commit()

    # Upload 600 bytes -> exceeds quota
    content = b"w" * 600
    md5_val = hashlib.md5(content).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "web_stage_overflow", content)
    assert await blob_storage.exists(USER_DATA_BUCKET, "web_stage_overflow") is True

    with pytest.raises(QuotaExceeded):
        await file_service.upload_finish_web(
            user=user,
            directory_id=0,
            file_name="web_overflow.txt",
            md5=md5_val,
            inner_name="web_stage_overflow",
        )

    assert await blob_storage.exists(USER_DATA_BUCKET, "web_stage_overflow") is False
    assert await file_service.get_storage_usage(user) == 0


async def test_upload_finish_web_overwrite_accounts_for_net_size_change(
    file_service: FileService,
    blob_storage: BlobStorage,
    session_manager: DatabaseSessionManager,
    create_test_user: None,
    test_users: list[str],
    test_user_id: int,
) -> None:
    """Verify upload_finish_web accounts for net size change when overwriting active file."""
    user = test_users[0]

    # Set quota to 500 bytes
    async with session_manager.session() as session:
        user_row = (
            await session.execute(select(UserDO).where(UserDO.id == test_user_id))
        ).scalar_one()
        user_row.total_capacity = "500"
        await session.commit()

    # Initial upload 400 bytes
    c1 = b"a" * 400
    md5_1 = hashlib.md5(c1).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "web_b1", c1)
    await file_service.upload_finish_web(
        user=user,
        directory_id=0,
        file_name="web_file.txt",
        md5=md5_1,
        inner_name="web_b1",
    )
    assert await file_service.get_storage_usage(user) == 400

    # Overwrite with 350 bytes (net -50 bytes, smaller size) -> succeeds
    c2 = b"b" * 350
    md5_2 = hashlib.md5(c2).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "web_b2", c2)
    await file_service.upload_finish_web(
        user=user,
        directory_id=0,
        file_name="web_file.txt",
        md5=md5_2,
        inner_name="web_b2",
    )
    assert await file_service.get_storage_usage(user) == 350
    assert await blob_storage.exists(USER_DATA_BUCKET, "web_b1") is False
    assert await blob_storage.exists(USER_DATA_BUCKET, "web_b2") is True

    # Overwrite with 600 bytes (net +250 bytes, total 600 > 500) -> QuotaExceeded
    c3 = b"c" * 600
    md5_3 = hashlib.md5(c3).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "web_b3_overflow", c3)
    with pytest.raises(QuotaExceeded):
        await file_service.upload_finish_web(
            user=user,
            directory_id=0,
            file_name="web_file.txt",
            md5=md5_3,
            inner_name="web_b3_overflow",
        )

    assert await blob_storage.exists(USER_DATA_BUCKET, "web_b3_overflow") is False
    assert await blob_storage.exists(USER_DATA_BUCKET, "web_b2") is True
    assert await file_service.get_storage_usage(user) == 350


async def test_upload_apply_and_volume_free_space_enforcement(
    file_service: FileService,
    blob_storage: BlobStorage,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Verify pre-flight upload_apply checks and disk exhaustion checks for uncapped and default-capped users."""
    user = test_users[0]

    # Uncapped user: volume reports 500 bytes free -> 600-byte upload rejected at upload_apply
    with patch.object(blob_storage, "get_available_bytes", return_value=500):
        await file_service.check_upload_apply_device(user, "/doc.pdf", "doc.pdf", 400)
        await file_service.check_upload_apply_web(user, 0, "doc.pdf", 400)

        with pytest.raises(QuotaExceeded):
            await file_service.check_upload_apply_device(
                user, "/INBOX/big.pdf", "big.pdf", 600
            )
        with pytest.raises(QuotaExceeded):
            await file_service.check_upload_apply_web(user, 0, "big.pdf", 600)

    # Server default_user_quota = 500 bytes enforced when UserDO.total_capacity == "0"
    file_service.default_user_quota = 500
    content = b"d" * 400
    md5_val = hashlib.md5(content).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "def_quota_1", content)
    await file_service.finish_upload(user, "f1.txt", "/", md5_val, "def_quota_1")

    with pytest.raises(QuotaExceeded):
        await file_service.check_upload_apply_device(user, "/f2.txt", "f2.txt", 200)
    with pytest.raises(QuotaExceeded):
        await file_service.check_upload_apply_web(user, 0, "f2.txt", 200)

    # Overwriting f1.txt (400B) with 450B (net +50B, total 450B <= 500B) passes upload_apply
    await file_service.check_upload_apply_device(user, "/f1.txt", "f1.txt", 450)
    await file_service.check_upload_apply_web(user, 0, "f1.txt", 450)

    # Zero available bytes at commit time still succeeds once the blob is already staged on disk
    # (including overwrites that reclaim superseded blob space)
    file_service.default_user_quota = 0
    c_smaller = b"z" * 100
    md5_smaller = hashlib.md5(c_smaller).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "disk_full_overwrite", c_smaller)
    with patch.object(blob_storage, "get_available_bytes", return_value=0):
        overwritten = await file_service.finish_upload(
            user, "f1.txt", "/", md5_smaller, "disk_full_overwrite"
        )
    assert overwritten.size == 100
    assert await blob_storage.exists(USER_DATA_BUCKET, "disk_full_overwrite") is True
    assert await blob_storage.exists(USER_DATA_BUCKET, "def_quota_1") is False


async def test_concurrent_finish_upload_same_inner_name_preserves_committed_blob(
    file_service: FileService,
    blob_storage: BlobStorage,
    session_manager: DatabaseSessionManager,
    create_test_user: None,
    test_users: list[str],
    test_user_id: int,
) -> None:
    """Verify concurrent finish_upload calls for the same inner_name never delete a committed blob."""
    user = test_users[0]
    async with session_manager.session() as session:
        user_row = (
            await session.execute(select(UserDO).where(UserDO.id == test_user_id))
        ).scalar_one()
        user_row.total_capacity = "500"
        await session.commit()

    content = b"s" * 400
    md5_val = hashlib.md5(content).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "shared_race_key", content)

    results = await asyncio.gather(
        file_service.finish_upload(user, "first.txt", "/", md5_val, "shared_race_key"),
        file_service.finish_upload(user, "second.txt", "/", md5_val, "shared_race_key"),
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, BaseException)]
    quota_errors = [r for r in results if isinstance(r, QuotaExceeded)]
    assert len(successes) == 1
    assert len(quota_errors) == 1
    assert await blob_storage.exists(USER_DATA_BUCKET, "shared_race_key") is True
    assert await file_service.get_storage_usage(user) == 400
