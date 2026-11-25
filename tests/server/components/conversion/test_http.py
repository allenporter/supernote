"""HTTP route tests for `supernote.server.components.conversion.http`."""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.device import DeviceClient
from supernote.client.extended import ExtendedClient
from supernote.server.components.conversion import (
    CONVERSION_CONFIG_KEY,
    CONVERSION_SERVICE_KEY,
)
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.keys import BLOB_STORAGE_KEY, URL_SIGNER_KEY


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


async def test_note_to_png_returns_empty_when_preview_disabled(
    client: TestClient,
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
    test_note_path: Path,
) -> None:
    """Verify POST /api/file/note/to/png returns an empty list when web_notebook_preview is disabled."""
    await _seed_note_file(
        client, session_manager, test_user_id, 9204, "Disabled.note", test_note_path
    )
    assert client.app is not None
    client.app[CONVERSION_CONFIG_KEY].notebook_preview = False

    disabled_vo = await device_client.note_to_png(9204)
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


async def test_extended_note_cover_converts_only_first_page(
    client: TestClient,
    auth_headers: dict[str, str],
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify POST /api/extended/file/note/cover converts only page 0 and serves a valid PNG."""
    assert client.app is not None
    file_id = 9101
    multipage_note = Path("tests/testdata/mmujynya/stroller.note")
    await _seed_note_file(
        client, session_manager, test_user_id, file_id, "CoverOnly.note", multipage_note
    )

    cover_vo = await extended_client.get_note_cover(file_id=file_id)
    assert cover_vo.success is True
    assert cover_vo.url is not None
    assert f"/api/oss/png/{file_id}/0?" in cover_vo.url

    # Browser-style string fileId wire payload
    resp = await client.post(
        "/api/extended/file/note/cover",
        json={"fileId": str(file_id)},
        headers=auth_headers,
    )
    assert resp.status == 200

    conversion_service = client.app[CONVERSION_SERVICE_KEY]
    assert (
        await conversion_service.get_note_png_page("test@example.com", file_id, 1)
        is None
    )

    rel_url = "/" + cover_vo.url.split("/", 3)[3]
    png_resp = await client.get(rel_url)
    assert png_resp.status == 200
    assert (await png_resp.read()).startswith(b"\x89PNG")


async def test_extended_note_cover_returns_none_when_preview_disabled(
    client: TestClient,
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
    test_note_path: Path,
) -> None:
    """Verify POST /api/extended/file/note/cover returns url=None when preview is disabled."""
    await _seed_note_file(
        client, session_manager, test_user_id, 9102, "NoPreview.note", test_note_path
    )
    assert client.app is not None
    client.app[CONVERSION_CONFIG_KEY].notebook_preview = False

    disabled_vo = await extended_client.get_note_cover(file_id=9102)
    assert disabled_vo.success is True
    assert disabled_vo.url is None


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/extended/file/note/cover",
        "/api/file/note/to/png",
        "/api/file/note/to/pdf",
    ],
)
async def test_conversion_endpoints_reject_malformed_payload(
    client: TestClient,
    auth_headers: dict[str, str],
    endpoint: str,
) -> None:
    """Verify conversion POST endpoints return 400 on missing required fields."""
    resp = await client.post(endpoint, json={}, headers=auth_headers)
    assert resp.status == 400


@pytest.mark.parametrize(
    "path",
    [
        "/api/oss/png/notanint/0",
        "/api/oss/png/9201/notanint",
        "/api/oss/pdf/notanint",
        "/api/oss/pdf/9202?pages=bad",
    ],
)
async def test_oss_render_downloads_reject_invalid_path_or_query_params(
    client: TestClient,
    path: str,
) -> None:
    """Verify signed requests with malformed path or pages query params return 400."""
    assert client.app is not None
    signed_path = await client.app[URL_SIGNER_KEY].sign(
        path, user="test@example.com", single_use=False
    )
    resp = await client.get(signed_path)
    assert resp.status == 400


@pytest.mark.parametrize(
    "path",
    [
        "/api/oss/png/9201/0",
        "/api/oss/png/notanint/0",
        "/api/oss/pdf/9202",
        "/api/oss/pdf/notanint",
    ],
)
async def test_oss_render_downloads_reject_unsigned_requests(
    client: TestClient,
    path: str,
) -> None:
    """Verify unsigned requests are rejected before parsing path/query parameters."""
    resp = await client.get(path)
    assert resp.status in (401, 403)


@pytest.mark.parametrize(
    ("path", "signed_query_keys"),
    [
        ("/api/oss/png/99999/0", ()),
        ("/api/oss/pdf/99999", ("pages",)),
    ],
)
async def test_oss_render_downloads_return_404_when_not_cached(
    client: TestClient,
    path: str,
    signed_query_keys: tuple[str, ...],
) -> None:
    """Verify signed requests for uncached renders return 404 without rendering on the fly."""
    assert client.app is not None
    url_signer = client.app[URL_SIGNER_KEY]
    signed_path = await url_signer.sign(path, user="test@example.com", single_use=False)
    resp = await client.get(signed_path)
    assert resp.status == 404
