from supernote.client.device import DeviceClient
from supernote.client.web import WebClient
from supernote.models.base import BooleanEnum
from supernote.models.file import FileSortOrder, FileSortSequence


async def test_file_list_query(
    web_client: WebClient,
    device_client: DeviceClient,
) -> None:
    # 1. Create directory structure (Setup using Device Client / storage helper)
    # Root
    #  - FolderA
    #    - File1
    #    - File2

    # Create FolderA in Root
    await web_client.create_folder(parent_id=0, name="FolderA")

    # Create files in FolderA
    await device_client.upload_content("/FolderA/File1.txt", b"content1")
    await device_client.upload_content("/FolderA/File2.txt", b"content2")

    # We need the ID of FolderA.
    # Since we are testing Web Listing, let's use Web Listing to find the ID from root.
    root_list = await web_client.list_query(
        directory_id=0,
        order=FileSortOrder.FILENAME,
        sequence=FileSortSequence.ASC,
    )
    folder_a_entry = next(
        e for e in root_list.user_file_vo_list if e.file_name == "FolderA"
    )
    folder_a_id = int(folder_a_entry.id)

    # 2. Query List (The actual test)
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

    # 3. Pagination
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
    device_client: DeviceClient,
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
