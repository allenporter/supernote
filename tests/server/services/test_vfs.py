import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.file import UserFileDO
from supernote.server.services.vfs import VirtualFileSystem


async def test_vfs_directory_operations(db_session: AsyncSession) -> None:
    vfs = VirtualFileSystem(db_session)
    user_id = 999
    root_id = 0

    # Create Directory
    folder = await vfs.create_directory(user_id, root_id, "MyFolder")
    assert folder.id > 0
    assert folder.file_name == "MyFolder"
    assert folder.directory_id == root_id

    # Helper to check listing
    children = await vfs.list_directory(user_id, root_id)
    assert len(children) == 1
    assert children[0].id == folder.id

    # Create sub-directory
    subfolder = await vfs.create_directory(user_id, folder.id, "SubFolder")
    assert subfolder.directory_id == folder.id

    # List sub-directory
    sub_children = await vfs.list_directory(user_id, folder.id)
    assert len(sub_children) == 1
    assert sub_children[0].file_name == "SubFolder"


async def test_vfs_file_operations(db_session: AsyncSession) -> None:
    vfs = VirtualFileSystem(db_session)
    user_id = 888

    # Create File
    file_node = await vfs.create_or_update_file(
        user_id, 0, "test.txt", size=100, md5="hash", storage_key="test-key"
    )
    assert file_node.file_name == "test.txt"
    assert file_node.is_folder == "N"

    # Verify in list
    children = await vfs.list_directory(user_id, 0)
    assert len(children) == 1
    assert children[0].md5 == "hash"

    # Soft Delete
    deleted = await vfs.delete_node(user_id, file_node.id)
    assert deleted is True

    # Verify gone from list
    children = await vfs.list_directory(user_id, 0)
    assert len(children) == 0

    # Verify can't get
    node = await vfs.get_node_by_id(user_id, file_node.id)
    assert node is None


async def test_vfs_ensure_directory_path_category_resolution(
    db_session: AsyncSession,
) -> None:
    """Verify ensure_directory_path resolves 'Note' to NOTE/Note system folder."""
    vfs = VirtualFileSystem(db_session)
    user_id = 999
    note_dir = await vfs.create_directory(user_id, 0, "NOTE")
    note_subdir = await vfs.create_directory(user_id, note_dir.id, "Note")

    resolved_id = await vfs.ensure_directory_path(user_id, "Note")
    assert resolved_id == note_subdir.id


async def test_vfs_resolve_path_category_resolution(
    db_session: AsyncSession,
) -> None:
    """Verify resolve_path resolves 'Note' to NOTE/Note system folder."""
    vfs = VirtualFileSystem(db_session)
    user_id = 999
    note_dir = await vfs.create_directory(user_id, 0, "NOTE")
    note_subdir = await vfs.create_directory(user_id, note_dir.id, "Note")

    node = await vfs.resolve_path(user_id, "Note")
    assert node is not None
    assert node.id == note_subdir.id


async def test_vfs_resolve_mismatched_container_path(
    db_session: AsyncSession,
) -> None:
    """Verify resolve_path('DOCUMENT/Note') returns None and does not match NOTE/Note."""
    vfs = VirtualFileSystem(db_session)
    user_id = 999
    note_dir = await vfs.create_directory(user_id, 0, "NOTE")
    await vfs.create_directory(user_id, note_dir.id, "Note")
    await vfs.create_directory(user_id, 0, "DOCUMENT")

    # DOCUMENT/Note does not exist, so it must return None
    node = await vfs.resolve_path(user_id, "DOCUMENT/Note")
    assert node is None


async def _get_raw(db_session: AsyncSession, node_id: int) -> UserFileDO | None:
    """Fetch a UserFileDO regardless of is_active (get_node_by_id filters it out)."""
    stmt = select(UserFileDO).where(UserFileDO.id == node_id)
    result = await db_session.execute(stmt)
    return result.scalar_one_or_none()


async def test_vfs_delete_folder_cascades_to_descendants(
    db_session: AsyncSession,
) -> None:
    """Soft-deleting a folder marks all descendants inactive, not just itself."""
    vfs = VirtualFileSystem(db_session)
    user_id = 111

    folder = await vfs.create_directory(user_id, 0, "Folder")
    subfolder = await vfs.create_directory(user_id, folder.id, "Sub")
    file_node = await vfs.create_or_update_file(
        user_id, subfolder.id, "note.note", size=10, md5="h", storage_key="key-1"
    )

    assert await vfs.delete_node(user_id, folder.id) is True

    # All three are now inactive, including the nested file.
    for node_id in (folder.id, subfolder.id, file_node.id):
        raw = await _get_raw(db_session, node_id)
        assert raw is not None
        assert raw.is_active == "N"
        assert await vfs.get_node_by_id(user_id, node_id) is None

    # Only the top-level folder gets its own recycle bin entry.
    recycle_entries = await vfs.list_recycle(user_id)
    assert len(recycle_entries) == 1
    assert recycle_entries[0].file_id == folder.id


async def test_vfs_restore_folder_cascades_to_descendants(
    db_session: AsyncSession,
) -> None:
    """Restoring a folder from recycle bin reactivates its descendants too."""
    vfs = VirtualFileSystem(db_session)
    user_id = 112

    folder = await vfs.create_directory(user_id, 0, "Folder")
    file_node = await vfs.create_or_update_file(
        user_id, folder.id, "note.note", size=10, md5="h", storage_key="key-2"
    )
    await vfs.delete_node(user_id, folder.id)

    recycle_entries = await vfs.list_recycle(user_id)
    assert len(recycle_entries) == 1

    assert await vfs.restore_node(user_id, recycle_entries[0].id) is True

    assert await vfs.get_node_by_id(user_id, folder.id) is not None
    assert await vfs.get_node_by_id(user_id, file_node.id) is not None
    children = await vfs.list_directory(user_id, folder.id)
    assert len(children) == 1
    assert children[0].id == file_node.id


async def test_vfs_purge_recycle_deletes_underlying_rows(
    db_session: AsyncSession,
) -> None:
    """Purging a recycle entry removes the UserFileDO row(s), not just the index."""
    vfs = VirtualFileSystem(db_session)
    user_id = 113

    folder = await vfs.create_directory(user_id, 0, "Folder")
    file_node = await vfs.create_or_update_file(
        user_id, folder.id, "note.note", size=10, md5="h", storage_key="key-3"
    )
    await vfs.delete_node(user_id, folder.id)

    purged_files = await vfs.purge_recycle(user_id)

    # The nested file is returned for the caller to clean up blob/events.
    assert [f.id for f in purged_files] == [file_node.id]

    # Both the folder and the nested file are now gone entirely, not just inactive.
    assert await _get_raw(db_session, folder.id) is None
    assert await _get_raw(db_session, file_node.id) is None
    assert await vfs.list_recycle(user_id) == []


async def test_vfs_purge_expired_recycle_respects_cutoff(
    db_session: AsyncSession,
) -> None:
    """purge_expired_recycle only purges entries older than the given cutoff."""
    vfs = VirtualFileSystem(db_session)
    user_id = 114

    old_file = await vfs.create_or_update_file(
        user_id, 0, "old.txt", size=1, md5="h1", storage_key="old-key"
    )
    await vfs.delete_node(user_id, old_file.id)

    new_file = await vfs.create_or_update_file(
        user_id, 0, "new.txt", size=1, md5="h2", storage_key="new-key"
    )
    await vfs.delete_node(user_id, new_file.id)

    # Backdate the "old" entry's delete_time so it looks 60 days old.
    sixty_days_ms = 60 * 86400 * 1000
    recycle_entries = await vfs.list_recycle(user_id)
    old_entry = next(e for e in recycle_entries if e.file_id == old_file.id)
    old_entry.delete_time = int(time.time() * 1000) - sixty_days_ms
    await db_session.commit()

    cutoff_ms = int(time.time() * 1000) - (30 * 86400 * 1000)
    purged_files = await vfs.purge_expired_recycle(cutoff_ms)

    assert [f.id for f in purged_files] == [old_file.id]
    assert await _get_raw(db_session, old_file.id) is None
    # The recent entry is untouched.
    assert await _get_raw(db_session, new_file.id) is not None
    remaining = await vfs.list_recycle(user_id)
    assert [e.file_id for e in remaining] == [new_file.id]
