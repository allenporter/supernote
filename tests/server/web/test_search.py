from supernote.client.web import WebClient


async def test_search_by_filename(
    web_client: WebClient,
) -> None:
    """Test searching for files by filename."""

    # Create some test folders and files
    notes = await web_client.create_folder(parent_id=0, name="Notes")
    await web_client.create_folder(parent_id=0, name="Documents")
    await web_client.create_folder(parent_id=int(notes.id), name="Meeting")

    # Search for "Notes"
    data = await web_client.search(keyword="Notes")
    assert len(data.entries) == 1
    assert data.entries[0].name == "Notes"
    assert data.entries[0].tag == "folder"


async def test_search_case_insensitive(
    web_client: WebClient,
) -> None:
    """Test that search is case-insensitive."""

    # Create folder
    # Create folder
    await web_client.create_folder(parent_id=0, name="MyFolder")

    # Search with lowercase
    data = await web_client.search(keyword="myfolder")
    assert len(data.entries) == 1
    assert data.entries[0].name == "MyFolder"


async def test_search_partial_match(
    web_client: WebClient,
) -> None:
    """Test that search matches partial filenames."""

    # Create folders
    # Create folders
    await web_client.create_folder(parent_id=0, name="Meeting2024")
    await web_client.create_folder(parent_id=0, name="Meeting2023")
    await web_client.create_folder(parent_id=0, name="Notes")

    # Search for "Meeting"
    data = await web_client.search(keyword="Meeting")
    assert len(data.entries) == 2
    names = {entry.name for entry in data.entries}
    assert names == {"Meeting2024", "Meeting2023"}


async def test_search_no_results(
    web_client: WebClient,
) -> None:
    """Test search with no matching results."""

    # Create folder
    # Create folder
    await web_client.create_folder(parent_id=0, name="Notes")

    # Search for non-existent keyword
    data = await web_client.search(keyword="NonExistent")
    assert len(data.entries) == 0


async def test_search_path_reconstruction(
    web_client: WebClient,
) -> None:
    """Test that search returns the correct full path for nested files."""
    # Create /Nested/Folder/DeepTarget
    # Create /Nested/Folder/DeepTarget
    nested = await web_client.create_folder(parent_id=0, name="Nested")
    folder = await web_client.create_folder(parent_id=int(nested.id), name="Folder")
    await web_client.create_folder(parent_id=int(folder.id), name="DeepTarget")

    # Search for "DeepTarget"
    data = await web_client.search(keyword="DeepTarget")
    assert len(data.entries) == 1
    entry = data.entries[0]

    assert entry.name == "DeepTarget"
    assert entry.path_display == "/Nested/Folder/DeepTarget"
    assert entry.parent_path == "/Nested/Folder"
