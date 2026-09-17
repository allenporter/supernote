import asyncio
from pathlib import Path

import pytest

from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import Event, LocalEventBus, NoteDeletedEvent
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.user import UserService
from supernote.server.services.vfs import VirtualFileSystem

TEST_USERNAME = "test@example.com"


@pytest.fixture
def event_bus() -> LocalEventBus:
    return LocalEventBus()


@pytest.fixture
def file_service(
    storage_root: Path,
    blob_storage: BlobStorage,
    user_service: UserService,
    session_manager: DatabaseSessionManager,
    event_bus: LocalEventBus,
) -> FileService:
    return FileService(
        storage_root, blob_storage, user_service, session_manager, event_bus
    )


async def test_purge_expired_recycle_entries_deletes_blob_and_publishes_event(
    file_service: FileService,
    blob_storage: BlobStorage,
    session_manager: DatabaseSessionManager,
    event_bus: LocalEventBus,
    create_test_user: None,
    test_user_id: int,
) -> None:
    """A purged note file's blob content is deleted and a NoteDeletedEvent fires."""
    storage_key = "note-key-1"
    await blob_storage.put(USER_DATA_BUCKET, storage_key, b"note bytes")

    async with session_manager.session() as session:
        vfs = VirtualFileSystem(session)
        note = await vfs.create_or_update_file(
            test_user_id, 0, "notebook.note", size=10, md5="h", storage_key=storage_key
        )
        await vfs.delete_node(test_user_id, note.id)
        note_id = note.id

    received: list[NoteDeletedEvent] = []

    async def _on_note_deleted(event: Event) -> None:
        assert isinstance(event, NoteDeletedEvent)
        received.append(event)

    event_bus.subscribe(NoteDeletedEvent, _on_note_deleted)

    async with session_manager.session() as session:
        vfs = VirtualFileSystem(session)
        entries = await vfs.list_recycle(test_user_id)
        assert len(entries) == 1

    # retention_days=0 makes the just-deleted entry immediately eligible, once
    # the cutoff (computed "now") is safely past its delete_time.
    await asyncio.sleep(0.01)
    purged_count = await file_service.purge_expired_recycle_entries(retention_days=0)
    assert purged_count == 1

    # Event handlers run as fire-and-forget tasks; give the loop a turn.
    await asyncio.sleep(0.1)

    assert await blob_storage.exists(USER_DATA_BUCKET, storage_key) is False
    assert len(received) == 1
    assert received[0].file_id == note_id
    assert received[0].user_id == test_user_id


async def test_purge_expired_recycle_entries_keeps_blob_shared_with_a_copy(
    file_service: FileService,
    blob_storage: BlobStorage,
    session_manager: DatabaseSessionManager,
    create_test_user: None,
    test_user_id: int,
) -> None:
    """Deleting+purging an original doesn't destroy a copy's blob content.

    `copy_node` reuses the source's `storage_key` rather than duplicating the
    blob, so the blob must only be deleted once nothing references it anymore.
    """
    storage_key = "shared-key-1"
    await blob_storage.put(USER_DATA_BUCKET, storage_key, b"shared bytes")

    async with session_manager.session() as session:
        vfs = VirtualFileSystem(session)
        original = await vfs.create_or_update_file(
            test_user_id, 0, "orig.txt", size=10, md5="h", storage_key=storage_key
        )
        await vfs.copy_node(
            test_user_id, original.id, 0, autorename=True, new_name="orig.txt"
        )
        await vfs.delete_node(test_user_id, original.id)

    await asyncio.sleep(0.01)
    purged_count = await file_service.purge_expired_recycle_entries(retention_days=0)
    assert purged_count == 1

    # The copy still references the same physical blob, so it must survive.
    assert await blob_storage.exists(USER_DATA_BUCKET, storage_key) is True


async def test_clear_recycle_purges_and_cleans_up(
    file_service: FileService,
    blob_storage: BlobStorage,
    session_manager: DatabaseSessionManager,
    create_test_user: None,
    test_user_id: int,
) -> None:
    """clear_recycle (empty the whole bin) also deletes blob content, unlike before."""
    storage_key = "clear-key-1"
    await blob_storage.put(USER_DATA_BUCKET, storage_key, b"bytes")

    async with session_manager.session() as session:
        vfs = VirtualFileSystem(session)
        file_node = await vfs.create_or_update_file(
            test_user_id, 0, "file.txt", size=10, md5="h", storage_key=storage_key
        )
        await vfs.delete_node(test_user_id, file_node.id)

    await file_service.clear_recycle(TEST_USERNAME)

    assert await blob_storage.exists(USER_DATA_BUCKET, storage_key) is False
