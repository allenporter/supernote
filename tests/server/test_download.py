import urllib.parse
from typing import Awaitable, Callable

from aiohttp.test_utils import TestClient
from aiohttp.web import Application

from tests.conftest import TEST_USERNAME, UserStorageHelper

AiohttpClient = Callable[[Application], Awaitable[TestClient]]


async def test_download_file_with_spaces(
    client: TestClient,
    user_storage: UserStorageHelper,
    auth_headers: dict[str, str],
) -> None:
    # Create a test file with spaces
    filename = "2023 December.pdf"
    user_storage.create_file(TEST_USERNAME, f"EXPORT/{filename}", content="pdf content")

    # 1. Apply for download
    file_id = f"EXPORT/{filename}"
    resp = await client.post(
        "/api/file/3/files/download_v3",
        json={"equipmentNo": "SN123", "id": file_id},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    download_url = data["url"]

    # 2. Download the file
    parsed = urllib.parse.urlparse(download_url)
    query = urllib.parse.parse_qs(parsed.query)
    path_param = query["path"][0]

    resp_download = await client.get(
        "/api/file/download/data",
        params={"path": path_param},
        headers=auth_headers,
    )
    assert resp_download.status == 200
    content = await resp_download.text()
    assert content == "pdf content"


async def test_download_apply_url_encoding(
    client: TestClient,
    user_storage: UserStorageHelper,
    auth_headers: dict[str, str],
) -> None:
    # Check if the URL returned by download_apply is encoded
    filename = "2023 December.pdf"
    file_id = f"EXPORT/{filename}"

    # Create the file so it exists
    user_storage.create_file(TEST_USERNAME, f"EXPORT/{filename}", content="content")

    resp = await client.post(
        "/api/file/3/files/download_v3",
        json={"equipmentNo": "SN123", "id": file_id},
        headers=auth_headers,
    )
    data = await resp.json()
    url = data["url"]

    # We expect the URL to be encoded so it's valid
    assert "2023%20December.pdf" in url
