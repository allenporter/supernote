from supernote.client.web import WebClient
from supernote.models.file_web import FileSortOrder, FileSortSequence


async def test_empty_subdirectory_listing(web_client: WebClient) -> None:
    # Create a folder at root level
    folder_vo = await web_client.create_folder(parent_id=0, name="EmptyFolder")
    folder_id = int(folder_vo.id)

    # List the empty folder - this should NOT return 404
    res = await web_client.list_query(
        directory_id=folder_id,
        order=FileSortOrder.FILENAME,
        sequence=FileSortSequence.ASC,
    )
    assert res.success
    assert res.total == 0
    assert len(res.user_file_vo_list) == 0
