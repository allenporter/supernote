import pytest

from supernote.client.exceptions import ApiException
from supernote.client.web import WebClient


@pytest.mark.asyncio
async def test_web_rename(web_client: WebClient) -> None:
    # 1. Create a folder
    res = await web_client.create_folder(parent_id=0, name="OldName")
    folder_id = int(res.id)

    # 2. Rename it
    await web_client.file_rename(id=folder_id, new_name="NewName")

    # 3. Verify name change
    list_res = await web_client.list_query(directory_id=0)
    assert any(f.file_name == "NewName" for f in list_res.user_file_vo_list)
    assert not any(f.file_name == "OldName" for f in list_res.user_file_vo_list)


@pytest.mark.asyncio
async def test_web_rename_immutable_fails(web_client: WebClient) -> None:
    # 1. Find a system folder
    res = await web_client.list_query(directory_id=0)
    note_folder = next(f for f in res.user_file_vo_list if f.file_name == "Note")
    note_id = int(note_folder.id)

    # 2. Attempt rename
    with pytest.raises(ApiException) as excinfo:
        await web_client.file_rename(id=note_id, new_name="RenamedNote")
    assert "Cannot rename system directory" in str(excinfo.value)


@pytest.mark.asyncio
async def test_web_move_items(web_client: WebClient) -> None:
    # 1. Create source and target folders
    src_res = await web_client.create_folder(parent_id=0, name="Source")
    src_id = int(src_res.id)
    target_res = await web_client.create_folder(parent_id=0, name="Target")
    target_id = int(target_res.id)

    # Create item in source
    item_res = await web_client.create_folder(parent_id=src_id, name="ItemToMove")
    item_id = int(item_res.id)

    # 2. Move item
    await web_client.file_move(
        id_list=[item_id], directory_id=src_id, go_directory_id=target_id
    )

    # 3. Verify move
    src_list = await web_client.list_query(directory_id=src_id)
    assert not any(f.file_name == "ItemToMove" for f in src_list.user_file_vo_list)

    target_list = await web_client.list_query(directory_id=target_id)
    assert any(f.file_name == "ItemToMove" for f in target_list.user_file_vo_list)


@pytest.mark.asyncio
async def test_web_copy_items(web_client: WebClient) -> None:
    # 1. Create source and target folders
    src_res = await web_client.create_folder(parent_id=0, name="SourceCopy")
    src_id = int(src_res.id)
    target_res = await web_client.create_folder(parent_id=0, name="TargetCopy")
    target_id = int(target_res.id)

    # Create item in source
    item_res = await web_client.create_folder(parent_id=src_id, name="ItemToCopy")
    item_id = int(item_res.id)

    # 2. Copy item
    await web_client.file_copy(
        id_list=[item_id], directory_id=src_id, go_directory_id=target_id
    )

    # 3. Verify copy (exists in both)
    src_list = await web_client.list_query(directory_id=src_id)
    assert any(f.file_name == "ItemToCopy" for f in src_list.user_file_vo_list)

    target_list = await web_client.list_query(directory_id=target_id)
    assert any(f.file_name == "ItemToCopy" for f in target_list.user_file_vo_list)


@pytest.mark.asyncio
async def test_web_folder_list_query(web_client: WebClient) -> None:
    # 1. Create a folder
    res = await web_client.create_folder(parent_id=0, name="QueryFolder")
    folder_id = int(res.id)

    # 2. Query folder list
    resp = await web_client.folder_list_query(directory_id=0, id_list=[folder_id])

    # 3. Verify response
    assert resp.folder_vo_list
    folders = resp.folder_vo_list
    assert len(folders) == 1


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
