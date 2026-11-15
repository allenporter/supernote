import dataclasses
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient
from pytest_aiohttp import AiohttpClient
from sqlalchemy import select

from supernote.client.device import DeviceClient
from supernote.server.app import create_app
from supernote.server.config import ServerConfig
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.keys import FILE_SERVICE_KEY
from supernote.server.utils.paths import (
    get_conversion_pdf_path,
    get_page_png_path,
)


async def test_note_conversion_wrappers(
    client: TestClient,
    device_client: DeviceClient,
    storage_root: Path,
    test_note_path: Path,
) -> None:
    # 1. Setup: Upload the test note
    with test_note_path.open("rb") as f:
        note_content = f.read()

    filename = "test_conversion_wrapper.note"
    upload_res = await device_client.upload_content(
        path=f"/{filename}", content=note_content, equipment_no="SN_TEST"
    )
    assert upload_res.id is not None
    file_id = int(upload_res.id)

    # 2. Test PNG Conversion via wrapper
    png_pages = await device_client.get_note_png_pages(file_id)
    assert len(png_pages) > 0
    assert png_pages[0].startswith(b"\x89PNG")

    # 3. Test PDF Conversion via wrapper
    pdf_content = await device_client.get_note_pdf(file_id)
    assert pdf_content.startswith(b"%PDF")

    # Verify PDF is stored in CACHE_BUCKET and not USER_DATA_BUCKET
    file_service = client.app[FILE_SERVICE_KEY]
    user_email = "test@example.com"
    user_id = await file_service.user_service.get_user_id(user_email)
    file_info = await file_service.get_file_info_by_id(user_email, file_id)
    assert file_info is not None and file_info.md5 is not None
    pdf_key = get_conversion_pdf_path(user_id, file_id, file_info.md5)
    assert await file_service.blob_storage.exists(CACHE_BUCKET, pdf_key)
    assert not await file_service.blob_storage.exists(USER_DATA_BUCKET, pdf_key)


async def test_note_to_pdf_partial(
    device_client: DeviceClient,
    test_note_path: Path,
) -> None:
    # Use existing note from previous test or upload new one
    with test_note_path.open("rb") as f:
        note_content = f.read()

    upload_res = await device_client.upload_content(
        path="/test_partial.note", content=note_content, equipment_no="SN_TEST"
    )
    assert upload_res.id is not None
    file_id = int(upload_res.id)

    # Test PDF with specific page
    pdf_content = await device_client.get_note_pdf(file_id, page_no_list=[0])
    assert pdf_content.startswith(b"%PDF")


async def test_note_png_caching(
    client: TestClient,
    device_client: DeviceClient,
    test_note_path: Path,
    session_manager: DatabaseSessionManager,
) -> None:
    # Setup: Upload the test note
    with test_note_path.open("rb") as f:
        note_content = f.read()

    filename = "test_caching.note"
    upload_res = await device_client.upload_content(
        path=f"/{filename}", content=note_content, equipment_no="SN_TEST"
    )
    await device_client.sync_end(equipment_no="SN_TEST")
    assert upload_res.id is not None
    file_id = int(upload_res.id)

    file_service = client.app[FILE_SERVICE_KEY]

    # First conversion: runs PageHashingModule + PngConversionModule and saves PNGs to CACHE_BUCKET
    png_pages_first = await device_client.get_note_png_pages(file_id)
    assert len(png_pages_first) > 0

    # Retrieve file info to get the storage_key
    user_email = "test@example.com"
    file_info = await file_service.get_file_info_by_id(user_email, file_id)
    assert file_info is not None and file_info.md5 is not None
    storage_key = file_info.storage_key
    assert storage_key is not None

    # Verify PageHashingModule populated NotePageContentDO with hashes and PNGs are in CACHE_BUCKET
    async with session_manager.session() as session:
        pages = list(
            (
                await session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == file_id)
                    .order_by(NotePageContentDO.page_index)
                )
            )
            .scalars()
            .all()
        )
    assert len(pages) == len(png_pages_first)
    for page in pages:
        assert page.content_hash is not None
        png_key = get_page_png_path(file_id, page.page_id)
        assert await file_service.blob_storage.exists(CACHE_BUCKET, png_key)
        assert not await file_service.blob_storage.exists(USER_DATA_BUCKET, png_key)
        # Overwrite cached PNG in CACHE_BUCKET to prove subsequent conversions
        # serve the existing CACHE_BUCKET blob without re-rendering
        await file_service.blob_storage.put(CACHE_BUCKET, png_key, b"cached_png_bytes")

    png_pages_second = await device_client.get_note_png_pages(file_id)
    assert png_pages_second == [b"cached_png_bytes"] * len(png_pages_first)


@pytest.mark.parametrize(
    ("web_enabled", "web_notebook_preview", "gemini_api_key"),
    [
        (True, False, None),
        (True, False, "fake-gemini-key"),
        (False, True, None),
    ],
)
async def test_note_to_png_disabled_matrix(
    aiohttp_client: AiohttpClient,
    server_config: ServerConfig,
    auth_headers: dict[str, str],
    web_enabled: bool,
    web_notebook_preview: bool,
    gemini_api_key: str | None,
) -> None:
    """Verify /api/file/note/to/png returns empty page list when web or preview is disabled, even if Gemini is configured."""
    cfg = dataclasses.replace(
        server_config,
        web_enabled=web_enabled,
        web_notebook_preview=web_notebook_preview,
        gemini_api_key=gemini_api_key,
    )
    app = create_app(cfg)
    client = await aiohttp_client(app)

    resp = await client.post(
        "/api/file/note/to/png",
        json={"id": 99999},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data == {"success": True, "pngPageVOList": []}
