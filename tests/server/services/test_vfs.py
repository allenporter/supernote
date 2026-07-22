from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.services.vfs import VirtualFileSystem


async def _seed_category_containers(
    vfs: VirtualFileSystem, user_id: int
) -> tuple[int, int]:
    """Seed the canonical two-level tree a real user gets on registration.

    Returns the ids of the canonical ``NOTE/Note`` and ``DOCUMENT/Document``
    folders (where the device actually scans for files).
    """
    note = await vfs.create_directory(user_id, 0, "NOTE")
    note_child = await vfs.create_directory(user_id, note.id, "Note")
    await vfs.create_directory(user_id, note.id, "MyStyle")
    doc = await vfs.create_directory(user_id, 0, "DOCUMENT")
    doc_child = await vfs.create_directory(user_id, doc.id, "Document")
    return note_child.id, doc_child.id


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


async def test_ensure_directory_path_routes_flattened_root_into_container(
    db_session: AsyncSession,
) -> None:
    """A display path like ``Note/...`` must land under the canonical
    ``NOTE/Note`` container the device scans — not create a rogue root ``Note``."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1001
    note_child_id, _ = await _seed_category_containers(vfs, user_id)

    parent_id = await vfs.ensure_directory_path(user_id, "Note")

    # Resolved into the canonical container child, not a new root folder.
    assert parent_id == note_child_id
    root_children = {c.file_name for c in await vfs.list_directory(user_id, 0)}
    assert "Note" not in root_children  # no rogue root folder was created


async def test_ensure_directory_path_nested_under_container(
    db_session: AsyncSession,
) -> None:
    """A nested display path descends through the container child correctly."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1002
    note_child_id, _ = await _seed_category_containers(vfs, user_id)

    sub_id = await vfs.ensure_directory_path(user_id, "Note/SubFolder")

    sub = await vfs.get_node_by_id(user_id, sub_id)
    assert sub is not None
    assert sub.file_name == "SubFolder"
    assert sub.directory_id == note_child_id  # created under NOTE/Note


async def test_ensure_directory_path_prefers_canonical_over_rogue_root(
    db_session: AsyncSession,
) -> None:
    """When a rogue root ``Note`` already exists (from the old bug), a fresh
    upload must still resolve into the canonical container, not the rogue root."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1003
    note_child_id, _ = await _seed_category_containers(vfs, user_id)
    rogue = await vfs.create_directory(user_id, 0, "Note")

    parent_id = await vfs.ensure_directory_path(user_id, "Note")

    assert parent_id == note_child_id
    assert parent_id != rogue.id


async def test_ensure_directory_path_creates_plain_root_folder(
    db_session: AsyncSession,
) -> None:
    """Non-canonical top-level names are unaffected — created at the real root."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1004
    await _seed_category_containers(vfs, user_id)

    parent_id = await vfs.ensure_directory_path(user_id, "Projects")

    node = await vfs.get_node_by_id(user_id, parent_id)
    assert node is not None
    assert node.file_name == "Projects"
    assert node.directory_id == 0  # real root


async def test_resolve_path_finds_container_child_at_root(
    db_session: AsyncSession,
) -> None:
    """Reading a display path resolves into the container too, so a file
    uploaded as ``Note/foo.note`` is found again by the same path."""
    vfs = VirtualFileSystem(db_session)
    user_id = 1005
    note_child_id, doc_child_id = await _seed_category_containers(vfs, user_id)
    await vfs.create_or_update_file(
        user_id, note_child_id, "foo.note", size=1, md5="m", storage_key="k"
    )

    folder = await vfs.resolve_path(user_id, "Note")
    assert folder is not None
    assert folder.id == note_child_id

    file_node = await vfs.resolve_path(user_id, "Note/foo.note")
    assert file_node is not None
    assert file_node.file_name == "foo.note"

    doc = await vfs.resolve_path(user_id, "Document")
    assert doc is not None
    assert doc.id == doc_child_id
