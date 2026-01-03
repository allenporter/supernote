from supernote.client.file import FileClient
from supernote.models.base import BooleanEnum
from supernote.models.file import FileSortOrder, FileSortSequence


async def test_file_list_query(file_client: FileClient) -> None:
    # 1. Create directory structure
    # Root
    #  - FolderA
    #    - File1
    #    - File2

    # Create FolderA in Root
    await file_client.create_folder(path="/FolderA", equipment_no="test")

    # We need the ID of FolderA.
    root_list = await file_client.list_folder(path="/", equipment_no="test")
    folder_a_entry = next(e for e in root_list.entries if e.name == "FolderA")
    folder_a_id = int(folder_a_entry.id)

    # Create files in FolderA
    await file_client.upload_content("/FolderA/File1.txt", b"content1")
    await file_client.upload_content("/FolderA/File2.txt", b"content2")

    # 2. Query List

    # Query FolderA (by ID)
    res = await file_client.list_query(
        directory_id=folder_a_id,
        order=FileSortOrder.FILENAME,
        sequence=FileSortSequence.ASC,
    )

    assert res.total == 2
    filenames = [f.file_name for f in res.user_file_vo_list]
    assert sorted(filenames) == ["File1.txt", "File2.txt"]

    # Check details
    f1 = next(f for f in res.user_file_vo_list if f.file_name == "File1.txt")
    assert f1.size == len(b"content1")
    assert f1.directory_id == str(folder_a_id)
    # Check BooleanEnum value usage
    assert f1.is_folder == BooleanEnum.NO

    # 3. Pagination
    res_page1 = await file_client.list_query(
        directory_id=folder_a_id,
        order=FileSortOrder.FILENAME,
        sequence=FileSortSequence.ASC,
        page_no=1,
        page_size=1,
    )
    assert res_page1.total == 2
    assert len(res_page1.user_file_vo_list) == 1
    assert res_page1.user_file_vo_list[0].file_name == "File1.txt"

    res_page2 = await file_client.list_query(
        directory_id=folder_a_id,
        order=FileSortOrder.FILENAME,
        sequence=FileSortSequence.ASC,
        page_no=2,
        page_size=1,
    )
    assert len(res_page2.user_file_vo_list) == 1
    assert res_page2.user_file_vo_list[0].file_name == "File2.txt"


async def test_file_list_query_root(file_client: FileClient) -> None:
    # Test listing root (directory_id=0)
    await file_client.create_folder(path="/FolderRoot", equipment_no="test")

    res = await file_client.list_query(
        directory_id=0, order=FileSortOrder.FILENAME, sequence=FileSortSequence.ASC
    )

    assert any(
        f.file_name == "FolderRoot" and f.is_folder == BooleanEnum.YES
        for f in res.user_file_vo_list
    )
