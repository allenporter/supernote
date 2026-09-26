"""Unit tests for FileService validating VFS operations, blob coordination, and event publishing."""

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from supernote.models.user import UserRegisterDTO
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus, NoteDeletedEvent, NoteUpdatedEvent
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import (
    FileNotFound,
    FileService,
    HashMismatch,
)
from supernote.server.services.user import UserService


@pytest.fixture
def mock_event_bus() -> MagicMock:
    """Mock LocalEventBus for verifying published domain events."""
    mock = MagicMock(spec=LocalEventBus)
    mock.publish = AsyncMock()
    return mock


@pytest.fixture
def file_service(
    blob_storage: BlobStorage,
    user_service: UserService,
    session_manager: DatabaseSessionManager,
    mock_event_bus: MagicMock,
) -> FileService:
    """Fixture providing FileService with explicit DI dependencies."""
    return FileService(
        blob_storage=blob_storage,
        user_service=user_service,
        session_manager=session_manager,
        event_bus=mock_event_bus,
    )


async def test_file_service_initialization(
    blob_storage: BlobStorage,
    user_service: UserService,
    session_manager: DatabaseSessionManager,
    mock_event_bus: MagicMock,
) -> None:
    """Verify FileService initializes with explicit dependencies and binds attributes."""
    service = FileService(
        blob_storage=blob_storage,
        user_service=user_service,
        session_manager=session_manager,
        event_bus=mock_event_bus,
    )
    assert service.blob_storage is blob_storage
    assert service.user_service is user_service
    assert service.session_manager is session_manager
    assert service.event_bus is mock_event_bus
    assert not hasattr(service, "temp_dir")
    assert not hasattr(service, "storage_root")


async def test_create_and_list_directories(
    file_service: FileService,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Verify creating directories and listing them in flat and recursive modes."""
    user = test_users[0]

    # Create root level folder
    docs_folder = await file_service.create_directory(user, "/Documents")
    assert docs_folder.name == "Documents"
    assert docs_folder.is_folder is True
    assert docs_folder.id > 0

    # Create nested folder by parent ID
    work_folder = await file_service.create_directory_by_id(
        user, docs_folder.id, "Work"
    )
    assert work_folder.name == "Work"
    assert work_folder.is_folder is True
    assert work_folder.parent_id == docs_folder.id

    # Flat listing of root contains the created folder
    root_items = await file_service.list_folder(user, "/")
    assert any(
        item.id == docs_folder.id and item.name == "Documents" for item in root_items
    )

    # Flat listing of /Documents
    doc_items = await file_service.list_folder(user, "/Documents")
    assert len(doc_items) == 1
    assert doc_items[0].id == work_folder.id

    # Recursive listing of root includes created folders
    recursive_items = await file_service.list_folder(user, "/", recursive=True)
    item_ids = {item.id for item in recursive_items}
    assert docs_folder.id in item_ids
    assert work_folder.id in item_ids


async def test_list_folder_error_paths(
    file_service: FileService,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Verify list_folder raises FileNotFound on missing paths and invalid folder IDs."""
    user = test_users[0]

    with pytest.raises(FileNotFound):
        await file_service.list_folder(user, "/NonExistentPath")

    with pytest.raises(FileNotFound):
        await file_service.list_folder_by_id(user, 999999)


async def test_finish_upload_device_note_file(
    file_service: FileService,
    blob_storage: BlobStorage,
    mock_event_bus: MagicMock,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Verify device upload finalization creates metadata in VFS and publishes NoteUpdatedEvent."""
    user = test_users[0]
    content = b"sample note binary data"
    content_hash = hashlib.md5(content).hexdigest()
    inner_name = "device_blob_note_1"

    # Pre-populate blob storage
    await blob_storage.put(USER_DATA_BUCKET, inner_name, content)

    file_entity = await file_service.finish_upload(
        user=user,
        filename="meeting.note",
        path_str="/",
        content_hash=content_hash,
        inner_name=inner_name,
    )

    assert file_entity.name == "meeting.note"
    assert file_entity.size == len(content)
    assert file_entity.md5 == content_hash
    assert file_entity.is_folder is False

    # Verify NoteUpdatedEvent published
    mock_event_bus.publish.assert_awaited_once()
    event = mock_event_bus.publish.call_args[0][0]
    assert isinstance(event, NoteUpdatedEvent)
    assert event.file_id == file_entity.id


async def test_finish_upload_device_non_note_file(
    file_service: FileService,
    blob_storage: BlobStorage,
    mock_event_bus: MagicMock,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Verify device upload finalization of non-note file does not trigger NoteUpdatedEvent."""
    user = test_users[0]
    content = b"%PDF-1.4 sample pdf content"
    content_hash = hashlib.md5(content).hexdigest()
    inner_name = "device_blob_pdf_1"

    await blob_storage.put(USER_DATA_BUCKET, inner_name, content)

    file_entity = await file_service.finish_upload(
        user=user,
        filename="manual.pdf",
        path_str="/",
        content_hash=content_hash,
        inner_name=inner_name,
    )

    assert file_entity.name == "manual.pdf"
    assert file_entity.size == len(content)
    mock_event_bus.publish.assert_not_called()


async def test_finish_upload_integrity_checks(
    file_service: FileService,
    blob_storage: BlobStorage,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Verify finish_upload raises HashMismatch on corrupted payload and FileNotFound on missing blob."""
    user = test_users[0]
    content = b"valid content"
    real_hash = hashlib.md5(content).hexdigest()
    inner_name = "integrity_blob_1"

    await blob_storage.put(USER_DATA_BUCKET, inner_name, content)

    # Hash mismatch
    with pytest.raises(HashMismatch):
        await file_service.finish_upload(
            user=user,
            filename="file.txt",
            path_str="/",
            content_hash="invalid_md5_hash",
            inner_name=inner_name,
        )

    # Missing blob
    with pytest.raises(FileNotFound):
        await file_service.finish_upload(
            user=user,
            filename="file.txt",
            path_str="/",
            content_hash=real_hash,
            inner_name="non_existent_blob",
        )


async def test_upload_finish_web_success_and_errors(
    file_service: FileService,
    blob_storage: BlobStorage,
    mock_event_bus: MagicMock,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Verify web upload endpoint finalization, error paths, and note event publishing."""
    user = test_users[0]
    content = b"web uploaded note content"
    md5_hash = hashlib.md5(content).hexdigest()
    inner_name = "web_blob_note_1"

    await blob_storage.put(USER_DATA_BUCKET, inner_name, content)

    # Successful web upload
    await file_service.upload_finish_web(
        user=user,
        directory_id=0,
        file_name="web.note",
        md5=md5_hash,
        inner_name=inner_name,
    )

    file_info = await file_service.get_file_info(user, "/web.note")
    assert file_info is not None
    assert file_info.name == "web.note"
    assert file_info.size == len(content)

    # Note event published
    mock_event_bus.publish.assert_awaited_once()
    event = mock_event_bus.publish.call_args[0][0]
    assert isinstance(event, NoteUpdatedEvent)
    assert event.file_id == file_info.id

    # Web upload with hash mismatch
    with pytest.raises(HashMismatch):
        await file_service.upload_finish_web(
            user=user,
            directory_id=0,
            file_name="bad.note",
            md5="wrong_hash",
            inner_name=inner_name,
        )

    # Web upload with missing blob
    with pytest.raises(FileNotFound):
        await file_service.upload_finish_web(
            user=user,
            directory_id=0,
            file_name="missing.note",
            md5=md5_hash,
            inner_name="nonexistent_blob",
        )


async def test_get_file_info_and_path_info(
    file_service: FileService,
    blob_storage: BlobStorage,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Verify get_file_info, get_file_info_by_id, and get_path_info contract conformance."""
    user = test_users[0]

    # Root directory info
    root_entity = await file_service.get_file_info(user, "")
    assert root_entity is not None
    assert root_entity.id == 0
    assert root_entity.is_folder is True

    root_slash_entity = await file_service.get_file_info(user, "/")
    assert root_slash_entity is not None
    assert root_slash_entity.id == 0

    # Create folder and file
    await file_service.create_directory(user, "/Projects")
    content = b"project file"
    md5 = hashlib.md5(content).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "proj_blob", content)
    file_entity = await file_service.finish_upload(
        user, "plan.txt", "/Projects", md5, "proj_blob"
    )

    # Query by path and ID
    info_by_path = await file_service.get_file_info(user, "/Projects/plan.txt")
    assert info_by_path is not None
    assert info_by_path.id == file_entity.id

    info_by_id = await file_service.get_file_info_by_id(user, file_entity.id)
    assert info_by_id is not None
    assert info_by_id.name == "plan.txt"

    # Non-existent queries
    assert await file_service.get_file_info(user, "/NonExistent.txt") is None
    assert await file_service.get_file_info_by_id(user, 888888) is None

    # Path info contract
    path_info = await file_service.get_path_info(user, file_entity.id)
    assert not path_info.path.startswith("/")
    assert not path_info.path.endswith("/")
    assert not path_info.id_path.startswith("/")
    assert path_info.id_path.endswith(str(file_entity.id))


async def test_storage_usage_and_is_empty(
    file_service: FileService,
    blob_storage: BlobStorage,
    user_service: UserService,
    session_manager: DatabaseSessionManager,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Verify is_empty and get_storage_usage reflect user filesystem state."""
    user = test_users[0]

    # User with default system directories has 0 bytes usage but is not empty
    assert await file_service.get_storage_usage(user) == 0
    assert await file_service.is_empty(user) is False

    # A user without any VFS entries reports is_empty is True
    blank_email = "blank_user@example.com"
    async with session_manager.session() as session:
        await user_service._create_user_entry(
            session,
            UserRegisterDTO(
                email=blank_email,
                password=hashlib.md5(b"blank_pass").hexdigest(),
                user_name="Blank User",
            ),
            is_admin=False,
        )
        await session.commit()
    assert await file_service.is_empty(blank_email) is True

    # Add content
    content = b"storage usage test payload"
    md5 = hashlib.md5(content).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "usage_blob", content)
    await file_service.finish_upload(user, "test.txt", "/", md5, "usage_blob")

    assert await file_service.is_empty(user) is False
    assert await file_service.get_storage_usage(user) == len(content)


async def test_rename_move_and_copy(
    file_service: FileService,
    blob_storage: BlobStorage,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Verify renaming, moving, and copying items across user directory hierarchy."""
    user = test_users[0]
    folder_a = await file_service.create_directory(user, "/FolderA")
    folder_b = await file_service.create_directory(user, "/FolderB")

    content = b"item data"
    md5 = hashlib.md5(content).hexdigest()
    await blob_storage.put(USER_DATA_BUCKET, "item_blob", content)
    file_entity = await file_service.finish_upload(
        user, "original.txt", "/FolderA", md5, "item_blob"
    )

    # Rename
    await file_service.rename_item(user, file_entity.id, "renamed.txt")
    renamed = await file_service.get_file_info_by_id(user, file_entity.id)
    assert renamed is not None
    assert renamed.name == "renamed.txt"

    # Move to FolderB
    await file_service.move_item(user, file_entity.id, "/FolderB")
    moved = await file_service.get_file_info_by_id(user, file_entity.id)
    assert moved is not None
    assert moved.parent_id == folder_b.id

    # Copy to FolderA
    copied = await file_service.copy_item(
        user, file_entity.id, "/FolderA", autorename=False
    )
    assert copied.id != file_entity.id
    assert copied.parent_id == folder_a.id
    assert copied.name == "renamed.txt"


async def test_recycle_bin_lifecycle(
    file_service: FileService,
    blob_storage: BlobStorage,
    mock_event_bus: MagicMock,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Verify moving files to recycle bin, restoring, permanent deletion, and empty recycle."""
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

    mock_event_bus.publish.reset_mock()
    await file_service.delete_from_recycle(user, [recycle_id_2])
    assert len(await file_service.list_recycle(user)) == 0

    # Permanent purge of .note publishes NoteDeletedEvent
    mock_event_bus.publish.assert_awaited_once()
    delete_event = mock_event_bus.publish.call_args[0][0]
    assert isinstance(delete_event, NoteDeletedEvent)
    assert delete_event.file_id == file_entity.id


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

    # Upload original file
    orig_file = await file_service.finish_upload(
        user, "orig.txt", "/", md5, storage_key
    )

    # Copy the file
    copied_file = await file_service.copy_item(
        user, orig_file.id, to_path="/copy.txt", autorename=True
    )
    assert copied_file.storage_key == orig_file.storage_key

    # Soft-delete and permanently purge original file
    await file_service.delete_item(user, orig_file.id)
    recycle_orig = (await file_service.list_recycle(user))[0]
    await file_service.delete_from_recycle(user, [recycle_orig.id])

    # Physical blob survives because copy still references it!
    assert await blob_storage.exists(USER_DATA_BUCKET, storage_key) is True

    # Soft-delete and permanently purge copy
    await file_service.delete_item(user, copied_file.id)
    recycle_copy = (await file_service.list_recycle(user))[0]
    await file_service.delete_from_recycle(user, [recycle_copy.id])

    # Physical blob is deleted now that no references survive!
    assert await blob_storage.exists(USER_DATA_BUCKET, storage_key) is False


async def test_file_purge_multiple_files_shared_blob_single_deletion(
    file_service: FileService,
    blob_storage: BlobStorage,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Verify permanently purging multiple files sharing the same blob key executes exactly one blob deletion call."""
    user = test_users[0]
    content = b"shared content bytes 2"
    md5 = hashlib.md5(content).hexdigest()
    storage_key = "shared_key_2"
    await blob_storage.put(USER_DATA_BUCKET, storage_key, content)

    # Upload original and create two copies
    f1 = await file_service.finish_upload(user, "f1.txt", "/", md5, storage_key)
    f2 = await file_service.copy_item(user, f1.id, to_path="/f2.txt", autorename=True)
    f3 = await file_service.copy_item(user, f1.id, to_path="/f3.txt", autorename=True)

    # Soft delete all three
    await file_service.delete_item(user, f1.id)
    await file_service.delete_item(user, f2.id)
    await file_service.delete_item(user, f3.id)

    recycle_items = await file_service.list_recycle(user)
    recycle_ids = [r.id for r in recycle_items]
    assert len(recycle_ids) == 3

    delete_calls: list[tuple[str, str]] = []
    orig_delete = blob_storage.delete

    async def tracking_delete(bucket: str, key: str) -> None:
        delete_calls.append((bucket, key))
        await orig_delete(bucket, key)

    setattr(blob_storage, "delete", tracking_delete)

    # Purge all 3 in a single call
    await file_service.delete_from_recycle(user, recycle_ids)

    # Assert exactly ONE blob deletion call for storage_key
    matching_calls = [
        call for call in delete_calls if call == (USER_DATA_BUCKET, storage_key)
    ]
    assert len(matching_calls) == 1
    assert await blob_storage.exists(USER_DATA_BUCKET, storage_key) is False


async def test_file_multi_user_shared_blob_reference_counting(
    file_service: FileService,
    blob_storage: BlobStorage,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Verify physical blob survives across different users until all users purge their files."""
    user1 = test_users[0]
    user2 = "user2@example.com"
    await file_service.user_service.create_user(
        UserRegisterDTO(
            email=user2,
            password=hashlib.md5(b"password").hexdigest(),
            user_name="User Two",
        )
    )

    content = b"multi user content bytes"
    md5 = hashlib.md5(content).hexdigest()
    storage_key = "multi_user_key_1"
    await blob_storage.put(USER_DATA_BUCKET, storage_key, content)

    # User 1 uploads file
    f1 = await file_service.finish_upload(user1, "u1.txt", "/", md5, storage_key)

    # User 2 uploads/shares the same storage key (e.g. deduplicated upload)
    f2 = await file_service.finish_upload(user2, "u2.txt", "/", md5, storage_key)
    assert f1.storage_key == f2.storage_key == storage_key

    # User 1 soft deletes and purges
    await file_service.delete_item(user1, f1.id)
    recycle_u1 = (await file_service.list_recycle(user1))[0]
    purged, freed = await file_service.purge_recycle(
        user_id=await file_service.user_service.get_user_id(user1),
        recycle_ids=[recycle_u1.id],
    )
    assert purged == 1
    # 0 bytes freed because physical blob survives!
    assert freed == 0
    assert await blob_storage.exists(USER_DATA_BUCKET, storage_key) is True

    # User 2 soft deletes and purges
    await file_service.delete_item(user2, f2.id)
    recycle_u2 = (await file_service.list_recycle(user2))[0]
    purged2, freed2 = await file_service.purge_recycle(
        user_id=await file_service.user_service.get_user_id(user2),
        recycle_ids=[recycle_u2.id],
    )
    assert purged2 == 1
    assert freed2 == len(content)
    # Physical blob is now deleted
    assert await blob_storage.exists(USER_DATA_BUCKET, storage_key) is False


async def test_file_purge_blob_deletion_failure_does_not_count_bytes_freed(
    file_service: FileService,
    blob_storage: BlobStorage,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Verify bytes_freed is not incremented if the underlying storage delete fails."""
    user = test_users[0]
    content = b"content to fail delete"
    md5 = hashlib.md5(content).hexdigest()
    storage_key = "fail_key_1"
    await blob_storage.put(USER_DATA_BUCKET, storage_key, content)

    f = await file_service.finish_upload(user, "fail.txt", "/", md5, storage_key)
    await file_service.delete_item(user, f.id)
    recycle_item = (await file_service.list_recycle(user))[0]

    # Mock blob_storage.delete to raise OSError
    async def failing_delete(bucket: str, key: str) -> None:
        raise OSError("Disk I/O error")

    setattr(blob_storage, "delete", failing_delete)

    purged, freed = await file_service.purge_recycle(
        user_id=await file_service.user_service.get_user_id(user),
        recycle_ids=[recycle_item.id],
    )
    assert purged == 1
    # Bytes freed should be 0 because physical deletion failed
    assert freed == 0


async def test_file_purge_missing_blob_does_not_count_bytes_freed(
    file_service: FileService,
    blob_storage: BlobStorage,
    create_test_user: None,
    test_users: list[str],
) -> None:
    """Verify bytes_freed is 0 when purging a file whose physical blob is missing in storage."""
    user = test_users[0]
    content = b"content for missing blob test"
    md5 = hashlib.md5(content).hexdigest()
    storage_key = "missing_blob_key_1"
    # Do NOT put blob into blob_storage, or put and then delete it directly
    await blob_storage.put(USER_DATA_BUCKET, storage_key, content)
    f = await file_service.finish_upload(user, "missing.txt", "/", md5, storage_key)

    # Directly delete the blob behind the back of VFS so storage raises FileNotFoundError
    await blob_storage.delete(USER_DATA_BUCKET, storage_key)
    assert await blob_storage.exists(USER_DATA_BUCKET, storage_key) is False

    # Soft-delete the file
    await file_service.delete_item(user, f.id)
    recycle_item = (await file_service.list_recycle(user))[0]

    # Permanently purge: purged count is 1, but freed bytes must be 0 because blob was already gone
    purged, freed = await file_service.purge_recycle(
        user_id=await file_service.user_service.get_user_id(user),
        recycle_ids=[recycle_item.id],
    )
    assert purged == 1
    assert freed == 0
