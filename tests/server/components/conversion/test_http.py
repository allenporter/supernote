"""HTTP route tests for `supernote.server.components.conversion.http`."""

from __future__ import annotations

from pathlib import Path

from aiohttp.test_utils import TestClient

from supernote.client.device import DeviceClient
from supernote.client.extended import ExtendedClient
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.keys import BLOB_STORAGE_KEY, CONFIG_KEY


async def _seed_note_file(
    client: TestClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
    file_id: int,
    file_name: str,
    note_path: Path,
) -> None:
    assert client.app is not None
    storage_key = f"conversion_http_{file_id}.note"
    await client.app[BLOB_STORAGE_KEY].put(
        USER_DATA_BUCKET, storage_key, note_path.read_bytes()
    )
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=test_user_id,
                directory_id=0,
                file_name=file_name,
                is_folder="N",
                storage_key=storage_key,
                md5=f"md5_{file_id}",
            )
        )
        await session.commit()


async def test_note_to_png_and_oss_png_download(
    client: TestClient,
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
    test_note_path: Path,
) -> None:
    """Verify POST /api/file/note/to/png returns signed URLs served by GET /api/oss/png/*."""
    await _seed_note_file(
        client, session_manager, test_user_id, 9201, "Sketch.note", test_note_path
    )

    png_vo = await device_client.note_to_png(9201)
    assert len(png_vo.png_page_vo_list) >= 1
    assert png_vo.png_page_vo_list[0].page_no == 0

    pages = await device_client.get_note_png_pages(9201)
    assert len(pages) == len(png_vo.png_page_vo_list)
    assert pages[0].startswith(b"\x89PNG")

    assert client.app is not None
    client.app[CONFIG_KEY].web_notebook_preview = False
    disabled_vo = await device_client.note_to_png(9201)
    assert disabled_vo.png_page_vo_list == []


async def test_note_to_pdf_and_oss_pdf_download(
    client: TestClient,
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
    test_note_path: Path,
) -> None:
    """Verify POST /api/file/note/to/pdf returns a signed URL served by GET /api/oss/pdf/*."""
    await _seed_note_file(
        client, session_manager, test_user_id, 9202, "Export.note", test_note_path
    )

    pdf_vo = await device_client.note_to_pdf(9202, page_no_list=[0])
    assert pdf_vo.url is not None
    assert "/api/oss/pdf/9202?pages=0" in pdf_vo.url

    pdf_bytes = await device_client.get_note_pdf(9202, page_no_list=[0])
    assert pdf_bytes.startswith(b"%PDF")


async def test_extended_note_cover_and_validation(
    client: TestClient,
    auth_headers: dict[str, str],
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
    test_note_path: Path,
) -> None:
    """Verify POST /api/extended/file/note/cover returns a signed cover URL and rejects malformed payloads."""
    await _seed_note_file(
        client, session_manager, test_user_id, 9203, "Cover.note", test_note_path
    )

    cover_vo = await extended_client.get_note_cover(file_id=9203)
    assert cover_vo.success is True
    assert cover_vo.url is not None
    assert "/api/oss/png/9203/0?" in cover_vo.url

    resp = await client.post(
        "/api/extended/file/note/cover",
        json={},
        headers=auth_headers,
    )
    assert resp.status == 400
