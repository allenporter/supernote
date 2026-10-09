import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import RecycleFileDO, UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import ParentNotFound
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
    """Verify soft-deleting a folder cascades inactivation across all descendants."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1001

    # Create folder hierarchy
    parent = await vfs.create_directory(user_id, 0, "Docs")
    child_dir = await vfs.create_directory(user_id, parent.id, "Work")

    # Add blobs and files
    await blob_storage.put(USER_DATA_BUCKET, "k1", b"content1")
    await blob_storage.put(USER_DATA_BUCKET, "k2", b"content2")
    await vfs.create_or_update_file(
        user_id, parent.id, "root_doc.txt", size=8, md5="m1", storage_key="k1"
    )
    await vfs.create_or_update_file(
        user_id, child_dir.id, "sub_doc.txt", size=8, md5="m2", storage_key="k2"
    )

    # Pre-condition: active files exist
    assert await vfs.get_total_usage(user_id) == 16
    assert len(await vfs.search_files(user_id, "doc")) == 3  # Docs folder + 2 files
    assert len(await vfs.list_directory(user_id, parent.id)) == 2

    # Integrity before delete
    integrity = IntegrityService(session_manager, blob_storage)
    report_before = await integrity.verify_user_storage(user_id)
    assert report_before.orphans == 0
    assert report_before.scanned == 4  # 2 folders, 2 files

    # Soft-delete parent folder
    success = await vfs.delete_node(user_id, parent.id)
    assert success is True

    # Parent folder is not in root
    assert len(await vfs.list_directory(user_id, 0)) == 0
    # Descendants do not appear in active listings
    assert len(await vfs.list_directory(user_id, parent.id)) == 0
    assert len(await vfs.list_directory(user_id, child_dir.id)) == 0
    # Soft-deleted folder contents do not appear in search
    assert len(await vfs.search_files(user_id, "doc")) == 0
    # Soft-deleted folder contents do not contribute to storage usage
    assert await vfs.get_total_usage(user_id) == 0
    # IntegrityService passes with zero orphan errors
    report_after = await integrity.verify_user_storage(user_id)
    assert report_after.orphans == 0
    assert report_after.scanned == 0


async def test_restore_folder_reactivates_all_descendants(
    db_session: AsyncSession,
) -> None:
    """Verify restoring a folder reactivates all descendant files and clears child recycle entries."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1002

    # Create folder and two child files
    folder = await vfs.create_directory(user_id, 0, "Projects")
    file1 = await vfs.create_or_update_file(
        user_id, folder.id, "independent.txt", size=10, md5="m1", storage_key="k1"
    )
    file2 = await vfs.create_or_update_file(
        user_id, folder.id, "cascaded.txt", size=20, md5="m2", storage_key="k2"
    )

    # Independently delete file1
    assert await vfs.delete_node(user_id, file1.id) is True

    # Delete parent folder
    assert await vfs.delete_node(user_id, folder.id) is True

    # Check recycle bin contents
    recycle_items = await vfs.list_recycle(user_id)
    assert len(recycle_items) == 2
    folder_recycle = next(r for r in recycle_items if r.file_id == folder.id)

    # Restore parent folder
    assert await vfs.restore_node(user_id, folder_recycle.id) is True

    # Folder is active again
    active_folder = await vfs.get_node_by_id(user_id, folder.id)
    assert active_folder is not None
    assert active_folder.is_active == "Y"

    # Both file1 and file2 are reactivated
    active_file1 = await vfs.get_node_by_id(user_id, file1.id)
    assert active_file1 is not None
    assert active_file1.is_active == "Y"

    active_file2 = await vfs.get_node_by_id(user_id, file2.id)
    assert active_file2 is not None
    assert active_file2.is_active == "Y"

    # Recycle bin is now completely empty
    recycle_after = await vfs.list_recycle(user_id)
    assert len(recycle_after) == 0


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

    # Soft delete child, then soft delete parent
    await vfs.delete_node(user_id, child.id)
    await vfs.delete_node(user_id, folder.id)

    recycle_items = await vfs.list_recycle(user_id)
    child_recycle = next(r for r in recycle_items if r.file_id == child.id)

    # Restoring child while parent is inactive must fail with ParentNotFound
    with pytest.raises(ParentNotFound) as exc_info:
        await vfs.restore_node(user_id, child_recycle.id)
    assert "Parent directory is missing" in str(exc_info.value)

    # Permanently delete parent folder record from UserFileDO while child remains in recycle bin
    await db_session.execute(delete(UserFileDO).where(UserFileDO.id == folder.id))
    await db_session.commit()

    # Restoring child when parent is permanently purged must fail with ParentNotFound
    with pytest.raises(ParentNotFound) as exc_info2:
        await vfs.restore_node(user_id, child_recycle.id)
    assert "Parent directory is missing" in str(exc_info2.value)

    # Non-existent recycle id returns False
    assert await vfs.restore_node(user_id, 999999) is False


async def test_purge_folder_removes_all_descendants_and_recycle_entries(
    db_session: AsyncSession,
) -> None:
    """Verify permanently purging a folder removes all descendant file records and recycle bin entries."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1004

    # Structure: F1 / F2 / file2.txt, and F1 / file1.txt
    f1 = await vfs.create_directory(user_id, 0, "F1")
    f2 = await vfs.create_directory(user_id, f1.id, "F2")
    await vfs.create_or_update_file(
        user_id, f1.id, "file1.txt", size=5, md5="m1", storage_key="k1"
    )
    file2 = await vfs.create_or_update_file(
        user_id, f2.id, "file2.txt", size=10, md5="m2", storage_key="k2"
    )

    # Independently soft-delete file2 (creates its own RecycleFileDO)
    await vfs.delete_node(user_id, file2.id)

    # Soft-delete parent folder F1
    await vfs.delete_node(user_id, f1.id)

    recycle_entries = await vfs.list_recycle(user_id)
    assert len(recycle_entries) == 2  # F1 and file2
    f1_recycle = next(r for r in recycle_entries if r.file_id == f1.id)

    # Purge parent folder F1
    purged_nodes, purged_recycle = await vfs.purge_recycle(user_id, [f1_recycle.id])
    assert len(purged_recycle) == 1

    # Verify all UserFileDO records are gone from database
    stmt_user_files = select(UserFileDO).where(UserFileDO.user_id == user_id)
    remaining_files = (await db_session.execute(stmt_user_files)).scalars().all()
    assert len(remaining_files) == 0

    # Verify all RecycleFileDO records (including descendant file2) are gone
    stmt_recycle = select(RecycleFileDO).where(RecycleFileDO.user_id == user_id)
    remaining_recycle = (await db_session.execute(stmt_recycle)).scalars().all()
    assert len(remaining_recycle) == 0


async def test_deeply_nested_folder_soft_delete_and_restore(
    db_session: AsyncSession,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
) -> None:
    """Verify soft-deleting and restoring a deeply nested folder hierarchy (>100 levels) maintains tree invariants."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1005

    # Create a 120-level deeply nested folder structure
    depth = 120
    current_parent_id = 0
    folder_ids = []
    for i in range(depth):
        folder = await vfs.create_directory(user_id, current_parent_id, f"level_{i}")
        folder_ids.append(folder.id)
        current_parent_id = folder.id

    # Place a leaf file at the deepest level
    leaf_file = await vfs.create_or_update_file(
        user_id,
        current_parent_id,
        "leaf.txt",
        size=100,
        md5="deep_md5",
        storage_key="deep_key",
    )

    assert await vfs.get_total_usage(user_id) == 100

    # Soft-delete the top-level root folder
    root_id = folder_ids[0]
    assert await vfs.delete_node(user_id, root_id) is True

    # Total usage should immediately be 0
    assert await vfs.get_total_usage(user_id) == 0

    # All descendants should be cascaded to 'N'
    stmt = select(UserFileDO.is_active).where(
        UserFileDO.id.in_(folder_ids[1:] + [leaf_file.id])
    )
    statuses = (await db_session.execute(stmt)).scalars().all()
    assert all(status == "N" for status in statuses)

    # IntegrityService should report zero orphans
    integrity = IntegrityService(session_manager, blob_storage)
    report = await integrity.verify_user_storage(user_id)
    assert report.orphans == 0

    # Restore the top-level folder
    recycle_items = await vfs.list_recycle(user_id)
    root_recycle = next(r for r in recycle_items if r.file_id == root_id)
    assert await vfs.restore_node(user_id, root_recycle.id) is True

    # All descendants should be restored to 'Y'
    stmt_restored = select(UserFileDO.is_active).where(
        UserFileDO.id.in_(folder_ids + [leaf_file.id])
    )
    restored_statuses = (await db_session.execute(stmt_restored)).scalars().all()
    assert all(status == "Y" for status in restored_statuses)
    assert await vfs.get_total_usage(user_id) == 100


async def test_cyclic_folder_safety_during_delete_and_restore(
    db_session: AsyncSession,
) -> None:
    """Verify that circular directory references terminate safely without infinite loops."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1006

    f1 = await vfs.create_directory(user_id, 0, "Cycle1")
    f2 = await vfs.create_directory(user_id, f1.id, "Cycle2")
    f3 = await vfs.create_directory(user_id, f2.id, "Cycle3")

    # Manually introduce a cycle in the DB by making f1 a child of f3
    await db_session.execute(
        update(UserFileDO).where(UserFileDO.id == f1.id).values(directory_id=f3.id)
    )
    await db_session.commit()

    # Soft deleting f1 must terminate safely without hanging
    assert await vfs.delete_node(user_id, f1.id) is True

    # Temporarily reset f1 parent to root so parent validation passes on restore
    await db_session.execute(
        update(UserFileDO).where(UserFileDO.id == f1.id).values(directory_id=0)
    )
    await db_session.commit()

    recycle_items = await vfs.list_recycle(user_id)
    f1_rec = next(r for r in recycle_items if r.file_id == f1.id)

    # Introduce a cycle among descendants f2 and f3: f2 parent is f3, f3 parent is f2
    await db_session.execute(
        update(UserFileDO).where(UserFileDO.id == f2.id).values(directory_id=f3.id)
    )
    await db_session.commit()

    # Cascade restore must terminate safely without hanging
    assert await vfs.restore_node(user_id, f1_rec.id) is True


async def test_purge_large_batch_chunking(
    db_session: AsyncSession,
) -> None:
    """Verify that purge_recycle handles batches larger than SQLite parameter limits (>500 items)."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1007
    total_files = 550

    # Bulk create files directly into UserFileDO and RecycleFileDO
    user_files = [
        UserFileDO(
            user_id=user_id,
            directory_id=0,
            file_name=f"bulk_file_{i}.txt",
            is_folder="N",
            size=10,
            md5=f"hash_{i}",
            storage_key=f"key_{i}",
            create_time=1000,
            update_time=1000,
            is_active="N",
        )
        for i in range(total_files)
    ]
    db_session.add_all(user_files)
    await db_session.flush()

    recycle_entries = [
        RecycleFileDO(
            user_id=user_id,
            file_id=uf.id,
            file_name=uf.file_name,
            size=uf.size,
            is_folder=uf.is_folder,
            delete_time=1000,
        )
        for uf in user_files
    ]
    db_session.add_all(recycle_entries)
    await db_session.commit()

    # Verify 550 entries exist
    recycle_items = await vfs.list_recycle(user_id)
    assert len(recycle_items) == total_files

    # Purge without limit or with recycle_ids containing all 550 IDs
    recycle_ids = [r.id for r in recycle_items]
    purged_nodes, purged_entries = await vfs.purge_recycle(
        user_id=user_id,
        recycle_ids=recycle_ids,
    )

    assert len(purged_nodes) == total_files
    assert len(purged_entries) == total_files

    # Verify both UserFileDO and RecycleFileDO records are completely removed
    remaining_recycle = await vfs.list_recycle(user_id)
    assert len(remaining_recycle) == 0

    stmt = select(UserFileDO).where(UserFileDO.user_id == user_id)
    remaining_files = (await db_session.execute(stmt)).scalars().all()
    assert len(remaining_files) == 0


async def test_nested_folder_cascade_soft_delete_and_restore_with_independent_child_deletion(
    db_session: AsyncSession,
) -> None:
    """Verify deep nested folder cascade delete & restore leaves independently deleted descendants inactive."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1008

    # Root -> TopFolder -> SubFolder -> [FileIndepDeleted, FileActive]
    top_folder = await vfs.create_directory(user_id, 0, "TopFolder")
    sub_folder = await vfs.create_directory(user_id, top_folder.id, "SubFolder")
    file_indep = await vfs.create_or_update_file(
        user_id, sub_folder.id, "indep.txt", size=50, md5="h1", storage_key="k1"
    )
    file_active = await vfs.create_or_update_file(
        user_id, sub_folder.id, "active.txt", size=75, md5="h2", storage_key="k2"
    )

    # 1. User independently deletes file_indep
    await vfs.delete_node(user_id, file_indep.id)

    recycle_items = await vfs.list_recycle(user_id)
    assert len(recycle_items) == 1
    indep_recycle = recycle_items[0]
    assert indep_recycle.file_id == file_indep.id

    # 2. User deletes top_folder (cascading across sub_folder and file_active)
    await vfs.delete_node(user_id, top_folder.id)

    recycle_items_after_top_del = await vfs.list_recycle(user_id)
    assert len(recycle_items_after_top_del) == 2
    top_recycle = next(
        r for r in recycle_items_after_top_del if r.file_id == top_folder.id
    )

    # Neither folder nor files appear in active listings
    assert len(await vfs.list_directory(user_id, 0)) == 0
    assert len(await vfs.search_files(user_id, "txt")) == 0
    assert await vfs.get_total_usage(user_id) == 0

    # 3. User restores top_folder
    assert await vfs.restore_node(user_id, top_recycle.id) is True

    # TopFolder and SubFolder are active
    active_top = await vfs.get_node_by_id(user_id, top_folder.id)
    assert active_top is not None and active_top.is_active == "Y"

    active_sub = await vfs.get_node_by_id(user_id, sub_folder.id)
    assert active_sub is not None and active_sub.is_active == "Y"

    # Both files are reactivated
    active_f2 = await vfs.get_node_by_id(user_id, file_active.id)
    assert active_f2 is not None and active_f2.is_active == "Y"

    active_f1 = await vfs.get_node_by_id(user_id, file_indep.id)
    assert active_f1 is not None and active_f1.is_active == "Y"

    # Recycle bin is now empty (child recycle entry was cleared upon folder restore)
    recycle_after_top_restore = await vfs.list_recycle(user_id)
    assert len(recycle_after_top_restore) == 0

    # Storage usage accounts for both files
    assert await vfs.get_total_usage(user_id) == 125
