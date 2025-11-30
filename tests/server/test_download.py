import pytest
from pathlib import Path
from typing import Callable, Awaitable
from aiohttp.test_utils import TestClient
from aiohttp.web import Application
from supernote.server.app import create_app
import urllib.parse

AiohttpClient = Callable[[Application], Awaitable[TestClient]]


@pytest.fixture(autouse=True)
async def test_download_file_with_spaces(
    aiohttp_client: AiohttpClient,
    mock_storage: Path,
    auth_headers: dict[str, str],
) -> None:
    # Create a test file with spaces
    filename = "2023 December.pdf"
    test_file = mock_storage / "EXPORT" / filename
    test_file.write_text("pdf content")

    client = await aiohttp_client(create_app())

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

    # Check if URL is properly encoded in the response?
    # The current implementation does NOT encode it.
    # download_url will be http://.../api/file/download/data?path=EXPORT/2023 December.pdf

    # 2. Download the file
    # We need to extract the path from the URL returned.
    # If the client uses the URL as is, it might be an issue if it's not encoded.

    # Let's simulate what the client might do.
    # If the client takes the URL literally:
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
    aiohttp_client: AiohttpClient,
    mock_storage: Path,
    auth_headers: dict[str, str],
) -> None:
    # Check if the URL returned by download_apply is encoded
    filename = "2023 December.pdf"
    file_id = f"EXPORT/{filename}"

    # Create the file so it exists
    (mock_storage / "EXPORT" / filename).write_text("content")

    client = await aiohttp_client(create_app())

    resp = await client.post(
        "/api/file/3/files/download_v3",
        json={"equipmentNo": "SN123", "id": file_id},
        headers=auth_headers,
    )
    data = await resp.json()
    url = data["url"]

    # We expect the URL to be encoded so it's valid
    # e.g. ...?path=EXPORT%2F2023%20December.pdf
    assert "2023%20December.pdf" in url
