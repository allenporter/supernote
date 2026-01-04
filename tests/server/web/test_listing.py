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


async def test_list_query_returns_default_folders(
    web_client: WebClient,
) -> None:
    """Verify that default folders are returned when listing root directory."""
    # Query root directory (directory_id=0)
    res = await web_client.list_query(
        directory_id=0,
        order=FileSortOrder.FILENAME,
        sequence=FileSortSequence.ASC,
    )

    # Extract folder names
    folders = [
        f.file_name for f in res.user_file_vo_list if f.is_folder == BooleanEnum.YES
    ]

    # Verify all six visible folders are present in flattened view
    assert "Export" in folders
    assert "Inbox" in folders
    assert "Screenshot" in folders
    assert "Note" in folders
    assert "Document" in folders
    assert "MyStyle" in folders

    # Verify category containers are HIDDEN
    assert "NOTE" not in folders
    assert "DOCUMENT" not in folders

    # Verify each default folder has correct properties
    for folder_name in ["Export", "Inbox", "Screenshot", "Note", "Document", "MyStyle"]:
        folder_vo = next(f for f in res.user_file_vo_list if f.file_name == folder_name)
        assert folder_vo.is_folder == BooleanEnum.YES
        assert folder_vo.id is not None
        assert folder_vo.directory_id == "0"


async def test_list_query_returns_subdirectories(
    web_client: WebClient,
) -> None:
    """Verify that subdirectories are returned when listing a parent directory."""
    # Create a parent folder
    parent_folder = await web_client.create_folder(parent_id=0, name="ParentFolder")
    parent_id = int(parent_folder.id)

    # Create two subdirectories within the parent
    await web_client.create_folder(parent_id=parent_id, name="SubFolder1")
    await web_client.create_folder(parent_id=parent_id, name="SubFolder2")

    # Query the parent folder by ID
    res = await web_client.list_query(
        directory_id=parent_id,
        order=FileSortOrder.FILENAME,
        sequence=FileSortSequence.ASC,
    )

    # Verify both subdirectories are returned
    assert res.total == 2
    folder_names = [f.file_name for f in res.user_file_vo_list]
    assert sorted(folder_names) == ["SubFolder1", "SubFolder2"]

    # Verify each subdirectory has correct properties
    for folder in res.user_file_vo_list:
        assert folder.is_folder == BooleanEnum.YES
        assert folder.directory_id == str(parent_id)


async def test_create_root_directory(
    web_client: WebClient,
) -> None:
    """Verify that creating a root directory works and it appears in root listing."""
    # Create a new folder at root level
    new_folder = await web_client.create_folder(parent_id=0, name="NewRootFolder")

    # Verify the returned folder object
    assert new_folder.file_name == "NewRootFolder"
    assert int(new_folder.id) > 0

    # Query root directory to verify the folder appears
    res = await web_client.list_query(
        directory_id=0,
        order=FileSortOrder.FILENAME,
        sequence=FileSortSequence.ASC,
    )

    # Verify the new folder is in the listing
    folder_names = [
        f.file_name for f in res.user_file_vo_list if f.is_folder == BooleanEnum.YES
    ]
    assert "NewRootFolder" in folder_names

    # Verify the folder has correct properties
    new_folder_in_list = next(
        f for f in res.user_file_vo_list if f.file_name == "NewRootFolder"
    )
    assert new_folder_in_list.is_folder == BooleanEnum.YES
    assert new_folder_in_list.directory_id == "0"
    assert new_folder_in_list.id == new_folder.id


async def test_user_file_vo_all_fields_for_file(
    web_client: WebClient,
) -> None:
    """Verify all UserFileVO fields are populated correctly for a file."""
    # Create a folder to upload into
    folder = await web_client.create_folder(parent_id=0, name="TestFolder")
    folder_id = int(folder.id)

    # Upload a file with known content
    file_content = b"Test file content for field validation"
    file_name = "test_file.txt"
    await web_client.upload_file(
        parent_id=folder_id, name=file_name, content=file_content
    )

    # Query the folder to get the file
    res = await web_client.list_query(
        directory_id=folder_id,
        order=FileSortOrder.FILENAME,
        sequence=FileSortSequence.ASC,
    )

    assert res.total == 1
    file_vo = res.user_file_vo_list[0]

    # Verify all fields are present and correct
    assert file_vo.id is not None
    assert file_vo.id != ""
    assert int(file_vo.id) > 0

    assert file_vo.directory_id == str(folder_id)

    assert file_vo.file_name == file_name

    assert file_vo.size == len(file_content)

    assert file_vo.md5 is not None
    assert len(file_vo.md5) == 32  # MD5 hash is 32 hex characters

    assert file_vo.inner_name is not None
    # inner_name should be the MD5 hash for uploaded files
    assert file_vo.inner_name == file_vo.md5

    assert file_vo.is_folder == BooleanEnum.NO

    assert file_vo.create_time is not None
    assert file_vo.create_time > 0

    assert file_vo.update_time is not None
    assert file_vo.update_time > 0
    # Update time should be >= create time
    assert file_vo.update_time >= file_vo.create_time


async def test_user_file_vo_all_fields_for_folder(
    web_client: WebClient,
) -> None:
    """Verify all UserFileVO fields are populated correctly for a folder."""
    # Create a folder at root
    folder_name = "ComprehensiveTestFolder"
    created_folder = await web_client.create_folder(parent_id=0, name=folder_name)

    # Query root to get the folder in the listing
    res = await web_client.list_query(
        directory_id=0,
        order=FileSortOrder.FILENAME,
        sequence=FileSortSequence.ASC,
    )

    # Find our folder in the results
    folder_vo = next(f for f in res.user_file_vo_list if f.file_name == folder_name)

    # Verify all fields are present and correct
    assert folder_vo.id is not None
    assert folder_vo.id != ""
    assert int(folder_vo.id) > 0
    assert folder_vo.id == created_folder.id

    assert folder_vo.directory_id == "0"

    assert folder_vo.file_name == folder_name

    # Folders should have None or 0 for size
    assert folder_vo.size is None or folder_vo.size == 0

    # Folders should have None for md5
    assert folder_vo.md5 is None

    # Folders should have None for inner_name
    assert folder_vo.inner_name is None

    assert folder_vo.is_folder == BooleanEnum.YES

    assert folder_vo.create_time is not None
    assert folder_vo.create_time > 0

    assert folder_vo.update_time is not None
    assert folder_vo.update_time > 0
    # Update time should be >= create time
    assert folder_vo.update_time >= folder_vo.create_time


async def test_path_query(
    web_client: WebClient,
) -> None:
    """Verify that /api/file/path/query returns correct path and ID path."""
    # Create structure: Root -> Parent -> Child
    parent_vo = await web_client.create_folder(parent_id=0, name="Parent")
    parent_id = int(parent_vo.id)

    child_vo = await web_client.create_folder(parent_id=parent_id, name="Child")
    child_id = int(child_vo.id)

    # Query Path for Child
    info = await web_client.path_query(id=child_id)
    assert info.success
    assert info.path == "Parent/Child/"
    # idPath should be "parent_id/child_id/"
    assert info.id_path == f"{parent_id}/{child_id}/"

    # Query Path for Parent
    info_p = await web_client.path_query(id=parent_id)
    assert info_p.path == "Parent/"
    assert info_p.id_path == f"{parent_id}/"


async def test_path_query_flattening(
    web_client: WebClient,
) -> None:
    """Verify that /api/file/path/query flattens categorized folders."""
    # Find Note folder (physically at /NOTE/Note)
    res = await web_client.list_query(directory_id=0)
    note_folder = next(f for f in res.user_file_vo_list if f.file_name == "Note")
    note_id = int(note_folder.id)

    # Query Path for Note
    info = await web_client.path_query(id=note_id)
    assert info.success
    # Should be flattened to just "Note/"
    assert info.path == "Note/"
    # idPath should be "note_id/"
    assert info.id_path == f"{note_id}/"


async def test_list_query_flattening(
    web_client: WebClient,
) -> None:
    """Verify that root listing flattens categorized folders and hides containers."""
    res = await web_client.list_query(directory_id=0)
    assert res.success

    folder_names = [
        f.file_name for f in res.user_file_vo_list if f.is_folder == BooleanEnum.YES
    ]

    # Verify all categorized folders are at root level
    assert "Export" in folder_names
    assert "Inbox" in folder_names
    assert "Screenshot" in folder_names
    assert "Note" in folder_names
    assert "Document" in folder_names
    assert "MyStyle" in folder_names

    # Verify container folders are HIDDEN from web API
    assert "NOTE" not in folder_names
    assert "DOCUMENT" not in folder_names

    # Verify flattened folders show directoryId=0
    note_folder = next(f for f in res.user_file_vo_list if f.file_name == "Note")
    assert note_folder.directory_id == "0"

    doc_folder = next(f for f in res.user_file_vo_list if f.file_name == "Document")
    assert doc_folder.directory_id == "0"
