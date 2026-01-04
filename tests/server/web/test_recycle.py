import pytest

from supernote.client.exceptions import ApiException
from supernote.client.web import WebClient


async def test_soft_delete_to_recycle(
    web_client: WebClient,
) -> None:
    # Create a folder
    await web_client.create_folder(parent_id=0, name="TestFolder")

    # Get ID of folder
    # Use Web Listing to find ID
    list_result = await web_client.list_query(directory_id=0)
    entry = next(
        e for e in list_result.user_file_vo_list if e.file_name == "TestFolder"
    )
    item_id = int(entry.id)

    # Delete (soft delete to recycle bin)
    await web_client.file_delete(id_list=[item_id])

    # Verify not in main folder
    list_folder_result = await web_client.list_query(directory_id=0)
    assert not any(
        e.file_name == "TestFolder" for e in list_folder_result.user_file_vo_list
    )

    # Verify in recycle bin
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.total == 1
    assert recycle_list_result.recycle_file_vo_list
    assert len(recycle_list_result.recycle_file_vo_list) == 1
    assert recycle_list_result.recycle_file_vo_list[0].file_name == "TestFolder"
    assert recycle_list_result.recycle_file_vo_list[0].is_folder == "Y"


async def test_recycle_revert(
    web_client: WebClient,
) -> None:
    # Create and delete a folder
    await web_client.create_folder(parent_id=0, name="ToRestore")

    list_result = await web_client.list_query(directory_id=0)
    entry = next(e for e in list_result.user_file_vo_list if e.file_name == "ToRestore")
    item_id = int(entry.id)

    await web_client.file_delete(id_list=[item_id])

    # Get recycle bin item ID
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.recycle_file_vo_list
    assert len(recycle_list_result.recycle_file_vo_list) == 1
    recycle_id = int(recycle_list_result.recycle_file_vo_list[0].file_id)

    # Revert from recycle bin
    await web_client.recycle_revert(id_list=[recycle_id])

    # Verify back in main folder
    list_folder_result = await web_client.list_query(directory_id=0)
    assert any(e.file_name == "ToRestore" for e in list_folder_result.user_file_vo_list)

    # Verify not in recycle bin
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result.total == 0


async def test_recycle_permanent_delete(
    web_client: WebClient,
) -> None:
    # Create and delete a folder
    await web_client.create_folder(parent_id=0, name="ToDelete")

    list_result = await web_client.list_query(directory_id=0)
    entry = next(e for e in list_result.user_file_vo_list if e.file_name == "ToDelete")
    item_id = int(entry.id)

    await web_client.file_delete(id_list=[item_id])

    # Get recycle bin item ID
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.recycle_file_vo_list
    assert len(recycle_list_result.recycle_file_vo_list) == 1
    recycle_id = int(recycle_list_result.recycle_file_vo_list[0].file_id)

    # Permanently delete from recycle bin
    await web_client.recycle_delete(id_list=[recycle_id])

    # Verify not in recycle bin
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.total == 0


async def test_recycle_clear(
    web_client: WebClient,
) -> None:
    # Default folders
    list_folder_result = await web_client.list_query(directory_id=0)
    assert list_folder_result
    assert len(list_folder_result.user_file_vo_list) == 5

    # Create and delete multiple folders
    for name in ["Folder1", "Folder2", "Folder3"]:
        await web_client.create_folder(parent_id=0, name=name)

    list_result = await web_client.list_query(directory_id=0)
    assert list_result.total == 8

    # Delete everything
    ids_to_delete = [int(f.id) for f in list_result.user_file_vo_list]
    await web_client.file_delete(id_list=ids_to_delete)

    # Verify 8 items in recycle bin
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.total == 8

    # Clear recycle bin
    await web_client.recycle_clear()

    # Verify recycle bin is empty
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.total == 0


async def test_delete_wrong_parent(
    web_client: WebClient,
) -> None:
    # 1. Create Parent Folder (in Root)
    parent_vo = await web_client.create_folder(parent_id=0, name="ParentFolder")
    parent_id = int(parent_vo.id)

    # 2. Create Child Folder (in Parent)
    child_vo = await web_client.create_folder(parent_id=parent_id, name="ChildFolder")
    child_id = int(child_vo.id)

    # 3. Try to delete Child using WRONG parent (Root=0)
    with pytest.raises(ApiException) as excinfo:
        await web_client.file_delete(id_list=[child_id], parent_id=0)

    assert "File " in str(excinfo.value)
    assert "is not in directory 0" in str(excinfo.value)

    # 4. Delete Child using CORRECT parent
    await web_client.file_delete(id_list=[child_id], parent_id=parent_id)

    # 5. Verify deleted from parent
    # Note: list_query for parent
    list_result = await web_client.list_query(directory_id=parent_id)
    assert not any(f.id == str(child_id) for f in list_result.user_file_vo_list)
