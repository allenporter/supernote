from typing import Awaitable, Callable

from aiohttp import FormData
from aiohttp.test_utils import TestClient
from aiohttp.web import Application

from supernote.server.app import create_app
from supernote.server.services.storage import StorageService
from tests.conftest import TEST_USERNAME

AiohttpClient = Callable[[Application], Awaitable[TestClient]]


async def test_upload_file(
    aiohttp_client: AiohttpClient,
    storage_service: StorageService,
    auth_headers: dict[str, str],
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
    temp_file = storage_service.resolve_temp_path(TEST_USERNAME, filename)
    assert temp_file.exists()
    assert temp_file.read_bytes() == file_content
