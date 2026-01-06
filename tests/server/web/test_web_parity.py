import pytest

from supernote.client.exceptions import ApiException
from supernote.client.web import WebClient


@pytest.mark.asyncio
async def test_web_rename(web_client: WebClient) -> None:
    # Create a folder
    res = await web_client.create_folder(parent_id=0, name="OldName")
    folder_id = int(res.id)

    # Rename it
    await web_client.file_rename(id=folder_id, new_name="NewName")

    # Verify name change
    list_res = await web_client.list_query(directory_id=0)
    assert [f.file_name for f in list_res.user_file_vo_list] == [
        "Screenshot",
        "Note",
        "NewName",  # New folder
        "MyStyle",
        "Inbox",
        "Export",
        "Document",
    ]


@pytest.mark.asyncio
async def test_web_rename_immutable_fails(web_client: WebClient) -> None:
    # Find a system folder
    res = await web_client.list_query(directory_id=0)
    note_folder = next(f for f in res.user_file_vo_list if f.file_name == "Note")
    note_id = int(note_folder.id)

    # 2. Attempt rename
    with pytest.raises(ApiException, match="Cannot rename system directory"):
        await web_client.file_rename(id=note_id, new_name="RenamedNote")


@pytest.mark.asyncio
async def test_web_move_items(web_client: WebClient) -> None:
    # Create source and target folders
    src_res = await web_client.create_folder(parent_id=0, name="Source")
    src_id = int(src_res.id)
    target_res = await web_client.create_folder(parent_id=0, name="Target")
    target_id = int(target_res.id)

    # Create item in source
    item_res = await web_client.create_folder(parent_id=src_id, name="ItemToMove")
    item_id = int(item_res.id)

    # Move item
    await web_client.file_move(
        id_list=[item_id], directory_id=src_id, go_directory_id=target_id
    )

    # Verify move
    src_list = await web_client.list_query(directory_id=src_id)
    assert [f.file_name for f in src_list.user_file_vo_list] == []

    target_list = await web_client.list_query(directory_id=target_id)
    assert [f.file_name for f in target_list.user_file_vo_list] == ["ItemToMove"]


@pytest.mark.asyncio
async def test_web_copy_items(web_client: WebClient) -> None:
    # Create source and target folders
    src_res = await web_client.create_folder(parent_id=0, name="SourceCopy")
    src_id = int(src_res.id)
    target_res = await web_client.create_folder(parent_id=0, name="TargetCopy")
    target_id = int(target_res.id)

    # Create item in source
    item_res = await web_client.create_folder(parent_id=src_id, name="ItemToCopy")
    item_id = int(item_res.id)

    # Copy item
    await web_client.file_copy(
        id_list=[item_id], directory_id=src_id, go_directory_id=target_id
    )

    # Verify copy (exists in both)
    src_list = await web_client.list_query(directory_id=src_id)
    assert any(f.file_name == "ItemToCopy" for f in src_list.user_file_vo_list)

    target_list = await web_client.list_query(directory_id=target_id)
    assert any(f.file_name == "ItemToCopy" for f in target_list.user_file_vo_list)


@pytest.mark.asyncio
async def test_web_folder_list_query_spec(web_client: WebClient) -> None:
    """Comprehensive test for api/file/folder/list/query specification."""
    # Root Level Flattening and Ordering
    # Note: physically at /NOTE/Note
    # Document: physically at /DOCUMENT/Document
    # MyStyle: physically at root /MyStyle
    res = await web_client.folder_list_query(directory_id=0, id_list=[])
    folders = res.folder_vo_list

    # Check for presence and capitalization
    names = [f.file_name for f in folders]
    assert names == ["Note", "Document", "Export", "Inbox", "MyStyle", "Screenshot"]

    # Exclusion Filter (idList)
    note_id = int(next(f for f in folders if f.file_name == "Note").id)
    res_excl = await web_client.folder_list_query(directory_id=0, id_list=[note_id])
    names_excl = [f.file_name for f in res_excl.folder_vo_list]
    assert names_excl == ["Document", "Export", "Inbox", "MyStyle", "Screenshot"]

    # Self-Exclusion (Folder hidden when in id_list)
    # Create a folder
    self_excl_res = await web_client.create_folder(
        parent_id=0, name="SelfExclusionFolder"
    )
    self_excl_id = int(self_excl_res.id)

    # Query Root with this folder in id_list -> should be excluded
    res_self_excl = await web_client.folder_list_query(
        directory_id=0, id_list=[self_excl_id]
    )
    names_self_excl = [f.file_name for f in res_self_excl.folder_vo_list]
    assert names_self_excl == [
        "Note",
        "Document",
        "Export",
        "Inbox",
        "MyStyle",
        "Screenshot",
    ]

    # isEmpty Lookahead (sub-folders only)
    # Create a folder with a file (should be empty=Y because it only checks for folders)
    await web_client.create_folder(parent_id=0, name="ParentFolder")
    root_res = await web_client.folder_list_query(directory_id=0, id_list=[])
    parent_vo = next(
        f for f in root_res.folder_vo_list if f.file_name == "Parentfolder"
    )
    parent_id = int(parent_vo.id)
    assert parent_vo.empty == "Y"

    # Add a sub-folder (should become empty=N)
    await web_client.create_folder(parent_id=parent_id, name="SubFolder")
    root_res_2 = await web_client.folder_list_query(directory_id=0, id_list=[])
    parent_vo_2 = next(
        f for f in root_res_2.folder_vo_list if f.file_name == "Parentfolder"
    )
    assert parent_vo_2.empty == "N"

    # Check the sub-folder itself (should be empty=Y)
    sub_res = await web_client.folder_list_query(directory_id=parent_id, id_list=[])
    sub_vo = next(f for f in sub_res.folder_vo_list if f.file_name == "SubFolder")
    assert sub_vo.empty == "Y"


@pytest.mark.asyncio
async def test_web_pages_1_even_if_empty(web_client: WebClient) -> None:
    # 1. Clear recycle bin to ensure it's empty
    await web_client.recycle_clear()

    # 2. Query recycle bin
    recycle_res = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_res.total == 0

    # 3. Query an empty directory
    res = await web_client.create_folder(parent_id=0, name="EmptyForPages")
    folder_id = int(res.id)
    list_res = await web_client.list_query(directory_id=folder_id)
    assert list_res.total == 0
    assert list_res.pages == 1


@pytest.mark.asyncio
async def test_web_search_path_flattening(web_client: WebClient) -> None:
    # Note is physically at /NOTE/Note
    # Search should report /Note
    search_res = await web_client.search(keyword="Note")
    note_entry = next(e for e in search_res.entries if e.name == "Note")
    assert note_entry.path_display == "Note"
    assert note_entry.parent_path == ""


async def test_web_move_identity_autorenames(web_client: WebClient) -> None:
    """Test identity move/copy (no-op)

    This exercises the case where the move/copy is a no-op, as the source and destination are the same.
    """
    res = await web_client.create_folder(parent_id=0, name="A")
    folder_id = int(res.id)

    # Move /A to / (its own parent)
    await web_client.file_move(id_list=[folder_id], directory_id=0, go_directory_id=0)

    # Check for A (1)
    list_res = await web_client.list_query(directory_id=0)
    names = [f.file_name for f in list_res.user_file_vo_list]
    assert "A (1)" in names


async def test_web_move_cyclic_fails(web_client: WebClient) -> None:
    """Test cyclic moves (failure)"""
    res_a = await web_client.create_folder(parent_id=0, name="A")
    id_a = int(res_a.id)
    res_b = await web_client.create_folder(parent_id=id_a, name="B")
    id_b = int(res_b.id)

    # Try to move A into B
    with pytest.raises(ApiException, match="Cyclic"):
        await web_client.file_move(id_list=[id_a], directory_id=0, go_directory_id=id_b)


async def test_web_move_invalid_dest_fails(web_client: WebClient) -> None:
    """Test invalid destinations (failure)"""
    res = await web_client.create_folder(parent_id=0, name="A")
    id_a = int(res.id)

    with pytest.raises(ApiException, match="not found"):
        await web_client.file_move(
            id_list=[id_a], directory_id=0, go_directory_id=999999
        )


async def test_web_move_root_fails(web_client: WebClient) -> None:
    """Test moving the root (failure)"""
    with pytest.raises(ApiException):
        await web_client.file_move(
            id_list=[0],
            directory_id=0,
            go_directory_id=1,  # Assuming 1 is some folder
        )


async def test_web_recursive_copy(web_client: WebClient) -> None:
    """Test recursive copy (deep hierarchy)"""
    res_src = await web_client.create_folder(parent_id=0, name="Src")
    src_id = int(res_src.id)
    await web_client.create_folder(parent_id=src_id, name="Sub")

    # Copy Src to Dest
    res_dest = await web_client.create_folder(parent_id=0, name="Dest")
    dest_id = int(res_dest.id)

    await web_client.file_copy(
        id_list=[src_id], directory_id=0, go_directory_id=dest_id
    )

    # Verify Dest/Src/Sub exists
    list_dest = await web_client.list_query(directory_id=dest_id)
    new_src = next(f for f in list_dest.user_file_vo_list if f.file_name == "Src")
    new_src_id = int(new_src.id)

    list_new_src = await web_client.list_query(directory_id=new_src_id)
    assert [f.file_name for f in list_new_src.user_file_vo_list] == ["Sub"]
