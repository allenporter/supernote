from supernote.client.device import DeviceClient
from supernote.client.web import WebClient


async def test_search_by_filename(
    web_client: WebClient, device_client: DeviceClient
) -> None:
    """Test searching for files by filename."""

    # Create some test folders and files
    await device_client.create_folder(path="/Notes", equipment_no="SN123456")
    await device_client.create_folder(path="/Documents", equipment_no="SN123456")
    await device_client.create_folder(path="/Notes/Meeting", equipment_no="SN123456")

    # Search for "Notes"
    data = await web_client.search(keyword="Notes")
    assert len(data.entries) == 1
    assert data.entries[0].name == "Notes"
    assert data.entries[0].tag == "folder"


async def test_search_case_insensitive(
    web_client: WebClient, device_client: DeviceClient
) -> None:
    """Test that search is case-insensitive."""

    # Create folder
    await device_client.create_folder(path="/MyFolder", equipment_no="SN123456")

    # Search with lowercase
    data = await web_client.search(keyword="myfolder")
    assert len(data.entries) == 1
    assert data.entries[0].name == "MyFolder"


async def test_search_partial_match(
    web_client: WebClient, device_client: DeviceClient
) -> None:
    """Test that search matches partial filenames."""

    # Create folders
    await device_client.create_folder(path="/Meeting2024", equipment_no="SN123456")
    await device_client.create_folder(path="/Meeting2023", equipment_no="SN123456")
    await device_client.create_folder(path="/Notes", equipment_no="SN123456")

    # Search for "Meeting"
    data = await web_client.search(keyword="Meeting")
    assert len(data.entries) == 2
    names = {entry.name for entry in data.entries}
    assert names == {"Meeting2024", "Meeting2023"}


async def test_search_no_results(
    web_client: WebClient, device_client: DeviceClient
) -> None:
    """Test search with no matching results."""

    # Create folder
    await device_client.create_folder(path="/Notes", equipment_no="SN123456")

    # Search for non-existent keyword
    data = await web_client.search(keyword="NonExistent")
    assert len(data.entries) == 0


async def test_search_path_reconstruction(
    web_client: WebClient, device_client: DeviceClient
) -> None:
    """Test that search returns the correct full path for nested files."""
    # Create /Nested/Folder/DeepTarget
    await device_client.create_folder(path="/Nested", equipment_no="SN123")
    await device_client.create_folder(path="/Nested/Folder", equipment_no="SN123")

    # Create a deep folder to search for
    await device_client.create_folder(
        path="/Nested/Folder/DeepTarget", equipment_no="SN123"
    )

    # Search for "DeepTarget"
    data = await web_client.search(keyword="DeepTarget")
    assert len(data.entries) == 1
    entry = data.entries[0]

    assert entry.name == "DeepTarget"
    assert entry.path_display == "/Nested/Folder/DeepTarget"
    assert entry.parent_path == "/Nested/Folder"
