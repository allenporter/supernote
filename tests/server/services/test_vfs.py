from sqlalchemy.ext.asyncio import AsyncSession

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
