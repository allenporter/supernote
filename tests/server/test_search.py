"""Tests for file search functionality."""

from supernote.server.app import create_app
from tests.conftest import AiohttpClient


async def test_search_by_filename(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str]
) -> None:
    """Test searching for files by filename."""
    client = await aiohttp_client(create_app())

    # Create some test folders and files
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/Notes"},
        headers=auth_headers,
    )
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/Documents"},
        headers=auth_headers,
    )
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/Notes/Meeting"},
        headers=auth_headers,
    )

    # Search for "Notes"
    resp = await client.post(
        "/api/file/label/list/search",
        json={"keyword": "Notes"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert len(data["entries"]) == 1
    assert data["entries"][0]["name"] == "Notes"
    assert data["entries"][0]["tag"] == "folder"


async def test_search_case_insensitive(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str]
) -> None:
    """Test that search is case-insensitive."""
    client = await aiohttp_client(create_app())

    # Create folder
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/MyFolder"},
        headers=auth_headers,
    )

    # Search with lowercase
    resp = await client.post(
        "/api/file/label/list/search",
        json={"keyword": "myfolder"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert len(data["entries"]) == 1
    assert data["entries"][0]["name"] == "MyFolder"


async def test_search_partial_match(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str]
) -> None:
    """Test that search matches partial filenames."""
    client = await aiohttp_client(create_app())

    # Create folders
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/Meeting2024"},
        headers=auth_headers,
    )
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/Meeting2023"},
        headers=auth_headers,
    )
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/Notes"},
        headers=auth_headers,
    )

    # Search for "Meeting"
    resp = await client.post(
        "/api/file/label/list/search",
        json={"keyword": "Meeting"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert len(data["entries"]) == 2
    names = {entry["name"] for entry in data["entries"]}
    assert names == {"Meeting2024", "Meeting2023"}


async def test_search_no_results(
    aiohttp_client: AiohttpClient, auth_headers: dict[str, str]
) -> None:
    """Test search with no matching results."""
    client = await aiohttp_client(create_app())

    # Create folder
    await client.post(
        "/api/file/2/files/create_folder_v2",
        json={"equipmentNo": "SN123456", "path": "/Notes"},
        headers=auth_headers,
    )

    # Search for non-existent keyword
    resp = await client.post(
        "/api/file/label/list/search",
        json={"keyword": "NonExistent"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert len(data["entries"]) == 0
