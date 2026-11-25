"""HTTP route tests for `supernote.server.components.conversion.http`."""

from __future__ import annotations

from pathlib import Path

from aiohttp.test_utils import TestClient

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
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
    test_note_path: Path,
) -> None:
    """Verify POST /api/file/note/to/png returns signed URLs served by GET /api/oss/png/*."""
    await _seed_note_file(
        client, session_manager, test_user_id, 9201, "Sketch.note", test_note_path
    )

    resp = await client.post(
        "/api/file/note/to/png",
        json={"id": "9201"},
        headers=auth_headers,
    )
    assert resp.status == 200
    payload = await resp.json()
    pages = payload["pngPageVOList"]
    assert len(pages) >= 1
    assert pages[0]["pageNo"] == 0

    rel_url = "/" + pages[0]["url"].split("/", 3)[3]
    png_resp = await client.get(rel_url)
    assert png_resp.status == 200
    assert (await png_resp.read()).startswith(b"\x89PNG")

    assert client.app is not None
    client.app[CONFIG_KEY].web_notebook_preview = False
    disabled_resp = await client.post(
        "/api/file/note/to/png",
        json={"id": "9201"},
        headers=auth_headers,
    )
    assert disabled_resp.status == 200
    assert (await disabled_resp.json())["pngPageVOList"] == []


async def test_note_to_pdf_and_oss_pdf_download(
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
    test_note_path: Path,
) -> None:
    """Verify POST /api/file/note/to/pdf returns a signed URL served by GET /api/oss/pdf/*."""
    await _seed_note_file(
        client, session_manager, test_user_id, 9202, "Export.note", test_note_path
    )

    resp = await client.post(
        "/api/file/note/to/pdf",
        json={"id": "9202", "pageNoList": [0]},
        headers=auth_headers,
    )
    assert resp.status == 200
    payload = await resp.json()
    assert "/api/oss/pdf/9202?pages=0" in payload["url"]

    rel_url = "/" + payload["url"].split("/", 3)[3]
    pdf_resp = await client.get(rel_url)
    assert pdf_resp.status == 200
    assert (await pdf_resp.read()).startswith(b"%PDF")


async def test_extended_note_cover_validation(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify POST /api/extended/file/note/cover rejects malformed payloads with 400."""
    resp = await client.post(
        "/api/extended/file/note/cover",
        json={},
        headers=auth_headers,
    )
    assert resp.status == 400
