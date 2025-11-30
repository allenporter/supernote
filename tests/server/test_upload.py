import pytest
from unittest.mock import patch
from pathlib import Path
from typing import Callable, Awaitable
from aiohttp import FormData
from aiohttp.test_utils import TestClient
from aiohttp.web import Application
from supernote.server.app import create_app

AiohttpClient = Callable[[Application], Awaitable[TestClient]]


@pytest.fixture(autouse=True)
def mock_storage(tmp_path: Path):
    storage_root = tmp_path / "storage"
    temp_root = tmp_path / "storage" / "temp"
    storage_root.mkdir(parents=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    with (
        patch("supernote.server.config.STORAGE_DIR", str(storage_root)),
        patch("supernote.server.config.TRACE_LOG_FILE", str(tmp_path / "trace.log")),
    ):
        yield storage_root


async def test_upload_file(
    aiohttp_client: AiohttpClient, mock_storage: Path, auth_headers: dict[str, str],
) -> None:
    client = await aiohttp_client(create_app())

    filename = "test_upload.note"
    file_content = b"some binary content"

    # Prepare multipart upload
    data = FormData()
    data.add_field("file", file_content, filename=filename)

    # Upload data
    # Note: The endpoint is /api/file/upload/data/{filename}
    # It accepts POST or PUT
    resp = await client.post(
        f"/api/file/upload/data/{filename}",
        data=data,
        headers=auth_headers,
    )
    assert resp.status == 200

    # Verify file exists in temp
    temp_file = mock_storage / "temp" / filename
    assert temp_file.exists()
    assert temp_file.read_bytes() == file_content
