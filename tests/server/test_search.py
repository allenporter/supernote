from supernote.client.file import FileClient


async def test_search_by_filename(file_client: FileClient) -> None:
    """Test searching for files by filename."""

    # Create some test folders and files
    await file_client.create_folder(path="/Notes", equipment_no="SN123456")
    await file_client.create_folder(path="/Documents", equipment_no="SN123456")
    await file_client.create_folder(path="/Notes/Meeting", equipment_no="SN123456")

    # Search for "Notes"
    data = await file_client.search(keyword="Notes")
    assert len(data.entries) == 1
    assert data.entries[0].name == "Notes"
    assert data.entries[0].tag == "folder"


async def test_search_case_insensitive(file_client: FileClient) -> None:
    """Test that search is case-insensitive."""

    # Create folder
    await file_client.create_folder(path="/MyFolder", equipment_no="SN123456")

    # Search with lowercase
    data = await file_client.search(keyword="myfolder")
    assert len(data.entries) == 1
    assert data.entries[0].name == "MyFolder"


async def test_search_partial_match(file_client: FileClient) -> None:
    """Test that search matches partial filenames."""

    # Create folders
    await file_client.create_folder(path="/Meeting2024", equipment_no="SN123456")
    await file_client.create_folder(path="/Meeting2023", equipment_no="SN123456")
    await file_client.create_folder(path="/Notes", equipment_no="SN123456")

    # Search for "Meeting"
    data = await file_client.search(keyword="Meeting")
    assert len(data.entries) == 2
    names = {entry.name for entry in data.entries}
    assert names == {"Meeting2024", "Meeting2023"}


async def test_search_no_results(file_client: FileClient) -> None:
    """Test search with no matching results."""

    # Create folder
    await file_client.create_folder(path="/Notes", equipment_no="SN123456")

    # Search for non-existent keyword
    data = await file_client.search(keyword="NonExistent")
    assert len(data.entries) == 0
