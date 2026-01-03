from supernote.client.web import WebClient
from supernote.models.base import BooleanEnum
from supernote.models.file import FileSortOrder, FileSortSequence


async def test_file_list_query(
    web_client: WebClient,
) -> None:
    # Create directory structure
    # Root
    #  - FolderA
    #    - File1
    #    - File2

    # Create FolderA in Root
    folder_vo = await web_client.create_folder(parent_id=0, name="FolderA")
    folder_a_id = int(folder_vo.id)

    # Create files in FolderA using WebClient
    await web_client.upload_file(
        parent_id=folder_a_id, name="File1.txt", content=b"content1"
    )
    await web_client.upload_file(
        parent_id=folder_a_id, name="File2.txt", content=b"content2"
    )

    # Query List (The actual test)
    # Query FolderA (by ID)
    res = await web_client.list_query(
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

    # Pagination
    res_page1 = await web_client.list_query(
        directory_id=folder_a_id,
        order=FileSortOrder.FILENAME,
        sequence=FileSortSequence.ASC,
        page_no=1,
        page_size=1,
    )
    assert res_page1.total == 2
    assert len(res_page1.user_file_vo_list) == 1
    assert res_page1.user_file_vo_list[0].file_name == "File1.txt"

    res_page2 = await web_client.list_query(
        directory_id=folder_a_id,
        order=FileSortOrder.FILENAME,
        sequence=FileSortSequence.ASC,
        page_no=2,
        page_size=1,
    )
    assert len(res_page2.user_file_vo_list) == 1
    assert res_page2.user_file_vo_list[0].file_name == "File2.txt"


async def test_file_list_query_root(
    web_client: WebClient,
) -> None:
    # Test listing root (directory_id=0)
    await web_client.create_folder(parent_id=0, name="FolderRoot")

    res = await web_client.list_query(
        directory_id=0, order=FileSortOrder.FILENAME, sequence=FileSortSequence.ASC
    )

    assert any(
        f.file_name == "FolderRoot" and f.is_folder == BooleanEnum.YES
        for f in res.user_file_vo_list
    )
