import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.base import ErrorCode
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import RecycleFileDO, UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import FileAlreadyExists, InvalidPath, ParentNotFound
from supernote.server.services.blob import BlobStorage
from supernote.server.services.integrity import IntegrityService
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


async def test_soft_delete_folder_cascades_inactivation(
    db_session: AsyncSession,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify soft-deleting a folder cascades inactivation across multiple folder layers."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1001

    parent = await vfs.create_directory(user_id, 0, "Docs")
    child_dir = await vfs.create_directory(user_id, parent.id, "Work")
    grandchild_dir = await vfs.create_directory(user_id, child_dir.id, "2026")

    m1 = (await blob_storage.put(USER_DATA_BUCKET, "key1", b"content1")).content_md5
    m2 = (await blob_storage.put(USER_DATA_BUCKET, "key2", b"content2")).content_md5
    m3 = (await blob_storage.put(USER_DATA_BUCKET, "key3", b"content3")).content_md5
    assert m1 and m2 and m3
    await vfs.create_or_update_file(
        user_id, parent.id, "root_doc.txt", size=8, md5=m1, storage_key="key1"
    )
    await vfs.create_or_update_file(
        user_id, child_dir.id, "sub_doc.txt", size=8, md5=m2, storage_key="key2"
    )
    await vfs.create_or_update_file(
        user_id, grandchild_dir.id, "deep_doc.txt", size=8, md5=m3, storage_key="key3"
    )

    assert await vfs.get_total_usage(user_id) == 24
    assert len(await vfs.search_files(user_id, "doc")) == 4
    assert len(await vfs.list_directory(user_id, parent.id)) == 2

    integrity = IntegrityService(session_manager, blob_storage)
    report_before = await integrity.verify_user_storage(user_id)
    assert report_before.issues == []
    assert report_before.scanned == 6

    assert await vfs.delete_node(user_id, parent.id) is True

    assert len(await vfs.list_directory(user_id, 0)) == 0
    assert len(await vfs.list_directory(user_id, parent.id)) == 0
    assert len(await vfs.list_directory(user_id, child_dir.id)) == 0
    assert len(await vfs.list_directory(user_id, grandchild_dir.id)) == 0
    assert len(await vfs.search_files(user_id, "doc")) == 0
    assert await vfs.get_total_usage(user_id) == 0

    report_after = await integrity.verify_user_storage(user_id)
    assert report_after.issues == []
    assert report_after.scanned == 0


async def test_restore_folder_selective_reactivation(
    db_session: AsyncSession,
) -> None:
    """Verify restoring a multi-layer folder reactivates cascaded descendants but not independently deleted files or subfolders."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1002

    # Layer 1 -> Layer 2 -> Layer 3
    folder = await vfs.create_directory(user_id, 0, "Projects")
    subfolder = await vfs.create_directory(user_id, folder.id, "Sub")
    deep_folder = await vfs.create_directory(user_id, subfolder.id, "Deep")
    file1 = await vfs.create_or_update_file(
        user_id, deep_folder.id, "independent.txt", size=10, md5="m1", storage_key="k1"
    )
    file2 = await vfs.create_or_update_file(
        user_id, deep_folder.id, "cascaded.txt", size=20, md5="m2", storage_key="k2"
    )

    # Second branch: an independently deleted subfolder with its own child file
    archived_sub = await vfs.create_directory(user_id, folder.id, "ArchivedSub")
    archived_file = await vfs.create_or_update_file(
        user_id, archived_sub.id, "archived.txt", size=30, md5="m3", storage_key="k3"
    )

    # Independently delete file1 and archived_sub before deleting top-level folder
    assert await vfs.delete_node(user_id, file1.id) is True
    assert await vfs.delete_node(user_id, archived_sub.id) is True
    assert await vfs.delete_node(user_id, folder.id) is True

    recycle_items = await vfs.list_recycle(user_id)
    assert len(recycle_items) == 3
    folder_recycle = next(r for r in recycle_items if r.file_id == folder.id)
    file1_recycle = next(r for r in recycle_items if r.file_id == file1.id)
    archived_recycle = next(r for r in recycle_items if r.file_id == archived_sub.id)

    # Restore top-level folder
    assert await vfs.restore_node(user_id, folder_recycle.id) is True

    # All 3 active folder layers and cascaded file2 are restored
    assert await vfs.get_node_by_id(user_id, folder.id) is not None
    assert await vfs.get_node_by_id(user_id, subfolder.id) is not None
    assert await vfs.get_node_by_id(user_id, deep_folder.id) is not None
    assert await vfs.get_node_by_id(user_id, file2.id) is not None

    # Independently deleted file1 and archived_sub (plus its child) remain inactive
    assert await vfs.get_node_by_id(user_id, file1.id) is None
    assert await vfs.get_node_by_id(user_id, archived_sub.id) is None
    assert await vfs.get_node_by_id(user_id, archived_file.id) is None
    for inactive_id in (file1.id, archived_sub.id, archived_file.id):
        stmt = select(UserFileDO).where(UserFileDO.id == inactive_id)
        assert (await db_session.execute(stmt)).scalar_one().is_active == "N"

    recycle_after = await vfs.list_recycle(user_id)
    assert {r.id for r in recycle_after} == {file1_recycle.id, archived_recycle.id}

    # Restoring archived_sub and file1 independently now succeeds
    assert await vfs.restore_node(user_id, archived_recycle.id) is True
    assert await vfs.get_node_by_id(user_id, archived_sub.id) is not None
    assert await vfs.get_node_by_id(user_id, archived_file.id) is not None

    assert await vfs.restore_node(user_id, file1_recycle.id) is True
    assert await vfs.get_node_by_id(user_id, file1.id) is not None


async def test_restore_fails_when_parent_missing_or_inactive(
    db_session: AsyncSession,
) -> None:
    """Verify restoring an item whose parent is inactive or missing fails with ParentNotFound."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1003

    folder = await vfs.create_directory(user_id, 0, "ParentDir")
    child = await vfs.create_or_update_file(
        user_id, folder.id, "child.txt", size=10, md5="m", storage_key="k"
    )

    await vfs.delete_node(user_id, child.id)
    await vfs.delete_node(user_id, folder.id)

    recycle_items = await vfs.list_recycle(user_id)
    child_recycle = next(r for r in recycle_items if r.file_id == child.id)

    with pytest.raises(ParentNotFound, match="Parent directory is missing"):
        await vfs.restore_node(user_id, child_recycle.id)

    await db_session.execute(delete(UserFileDO).where(UserFileDO.id == folder.id))
    await db_session.commit()

    with pytest.raises(ParentNotFound, match="Parent directory is missing"):
        await vfs.restore_node(user_id, child_recycle.id)

    assert await vfs.restore_node(user_id, 999999) is False


async def test_purge_folder_removes_all_descendants_and_recycle_entries(
    db_session: AsyncSession,
) -> None:
    """Verify permanently purging a folder removes all descendant file records and recycle bin entries."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1004

    f1 = await vfs.create_directory(user_id, 0, "F1")
    f2 = await vfs.create_directory(user_id, f1.id, "F2")
    await vfs.create_or_update_file(
        user_id, f1.id, "file1.txt", size=5, md5="m1", storage_key="k1"
    )
    file2 = await vfs.create_or_update_file(
        user_id, f2.id, "file2.txt", size=10, md5="m2", storage_key="k2"
    )

    await vfs.delete_node(user_id, file2.id)
    await vfs.delete_node(user_id, f1.id)

    recycle_entries = await vfs.list_recycle(user_id)
    assert len(recycle_entries) == 2
    f1_recycle = next(r for r in recycle_entries if r.file_id == f1.id)

    purged_nodes = await vfs.purge_recycle(user_id, [f1_recycle.id])
    assert len(purged_nodes) == 4

    remaining_files = (
        (
            await db_session.execute(
                select(UserFileDO).where(UserFileDO.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(remaining_files) == 0

    remaining_recycle = (
        (
            await db_session.execute(
                select(RecycleFileDO).where(RecycleFileDO.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(remaining_recycle) == 0


async def test_list_recursive_nested_hierarchy(
    db_session: AsyncSession,
) -> None:
    """Verify list_recursive traverses nested folders in memory and returns accurate relative paths."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1005

    root_dir = await vfs.create_directory(user_id, 0, "Note")
    sub_dir = await vfs.create_directory(user_id, root_dir.id, "Project")
    deep_dir = await vfs.create_directory(user_id, sub_dir.id, "2026")
    other_root = await vfs.create_directory(user_id, 0, "Document")

    await vfs.create_or_update_file(
        user_id, root_dir.id, "root.note", size=10, md5="m1", storage_key="k1"
    )
    await vfs.create_or_update_file(
        user_id, deep_dir.id, "deep.note", size=20, md5="m2", storage_key="k2"
    )
    await vfs.create_or_update_file(
        user_id, other_root.id, "other.pdf", size=30, md5="m3", storage_key="k3"
    )

    items = await vfs.list_recursive(user_id, root_dir.id)
    rel_paths = [rel_path for _, rel_path in items]
    assert rel_paths == [
        "Project",
        "Project/2026",
        "Project/2026/deep.note",
        "root.note",
    ]


async def test_get_folder_sizes_recursive_and_inactive_exclusion(
    db_session: AsyncSession,
) -> None:
    """Verify get_folder_sizes computes recursive active descendant file bytes per folder."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1006

    folder_a = await vfs.create_directory(user_id, 0, "FolderA")
    sub_a1 = await vfs.create_directory(user_id, folder_a.id, "SubA1")
    deep_a2 = await vfs.create_directory(user_id, sub_a1.id, "DeepA2")
    empty_folder = await vfs.create_directory(user_id, 0, "EmptyFolder")
    folder_b = await vfs.create_directory(user_id, 0, "FolderB")

    await vfs.create_or_update_file(
        user_id, folder_a.id, "top.note", size=100, md5="m1", storage_key="k1"
    )
    await vfs.create_or_update_file(
        user_id, sub_a1.id, "mid.note", size=250, md5="m2", storage_key="k2"
    )
    deleted_file = await vfs.create_or_update_file(
        user_id, deep_a2.id, "deleted.note", size=900, md5="m3", storage_key="k3"
    )
    await vfs.create_or_update_file(
        user_id, deep_a2.id, "deep.note", size=400, md5="m4", storage_key="k4"
    )
    await vfs.create_or_update_file(
        user_id, folder_b.id, "b.pdf", size=50, md5="m5", storage_key="k5"
    )

    # Soft-delete one descendant file and verify it is excluded
    await vfs.delete_node(user_id, deleted_file.id)

    assert await vfs.get_folder_sizes(user_id, []) == {}

    sizes = await vfs.get_folder_sizes(
        user_id, [folder_a.id, sub_a1.id, deep_a2.id, empty_folder.id, folder_b.id]
    )
    assert sizes == {
        folder_a.id: 750,
        sub_a1.id: 650,
        deep_a2.id: 400,
        empty_folder.id: 0,
        folder_b.id: 50,
    }


async def test_move_node_to_path_collision_identity_and_cycle_guards(
    db_session: AsyncSession,
) -> None:
    """Verify move_node_to_path treats to_path as target path, handles identity moves, and aborts cycles before creating subdirs."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1007

    note_root = await vfs.create_directory(user_id, 0, "Note")
    foo = await vfs.create_directory(user_id, note_root.id, "Foo")
    bar = await vfs.create_directory(user_id, note_root.id, "Bar")

    # Collision with existing folder Foo when autorename=False raises E0322 instead of moving Bar inside Foo
    with pytest.raises(FileAlreadyExists) as conflict_err:
        await vfs.move_node_to_path(user_id, bar.id, "/Note/Foo", autorename=False)
    assert conflict_err.value.error_code == ErrorCode.CONFLICT_EXISTS.value
    assert await vfs.list_directory(user_id, foo.id) == []

    # Collision with existing folder Foo when autorename=True renames to 'Foo (1)' in /Note
    moved_bar = await vfs.move_node_to_path(
        user_id, bar.id, "/Note/Foo", autorename=True
    )
    assert moved_bar is not None
    assert moved_bar.directory_id == note_root.id
    assert moved_bar.file_name == "Foo (1)"
    assert await vfs.list_directory(user_id, foo.id) == []

    # Identity move on folder Foo (autorename=False) is a no-op rather than a cyclic error
    noop_foo = await vfs.move_node_to_path(
        user_id, foo.id, "/Note/Foo", autorename=False
    )
    assert noop_foo is not None
    assert noop_foo.id == foo.id
    assert noop_foo.directory_id == note_root.id
    assert noop_foo.file_name == "Foo"

    # Case-only self-rename succeeds in place
    case_renamed = await vfs.move_node_to_path(
        user_id, foo.id, "/Note/foo", autorename=False
    )
    assert case_renamed is not None
    assert case_renamed.id == foo.id
    assert case_renamed.file_name == "foo"

    # Cyclic move with non-existent intermediate directories raises E0358 without creating orphan subdirs
    with pytest.raises(InvalidPath) as cycle_err:
        await vfs.move_node_to_path(
            user_id, foo.id, "/Note/foo/MissingSub/Moved", autorename=False
        )
    assert cycle_err.value.error_code == ErrorCode.CYCLIC_MOVE.value
    assert await vfs.list_directory(user_id, foo.id) == []

    # Empty destination path raises InvalidPath
    with pytest.raises(InvalidPath, match="Destination path cannot be empty"):
        await vfs.move_node_to_path(user_id, foo.id, "/", autorename=False)
