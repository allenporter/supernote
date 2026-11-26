"""HTTP platform tests for `supernote.server.components.note_metadata.http`."""

from __future__ import annotations

import io
from pathlib import Path

from aiohttp.test_utils import TestClient
from PIL import Image
from sqlalchemy import delete
from yarl import URL

from supernote.client.extended import ExtendedClient
from supernote.server.components.processor.page_hashing import PageHashingModule
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NoteMetadataDO,
    NotePageMetadataDO,
)
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.keys import BLOB_STORAGE_KEY, FILE_SERVICE_KEY

HEADING_NOTE_PATH = (
    Path(__file__).parents[3]
    / "testdata"
    / "philips"
    / "heading-n5-20260016-backgrounds-marker.note"
)


async def _hash_heading_note(
    client: TestClient, session_manager: DatabaseSessionManager, user_id: int
) -> int:
    assert client.app is not None
    file_id = 8811
    storage_key = "headings_8811.note"
    await client.app[BLOB_STORAGE_KEY].put(
        USER_DATA_BUCKET, storage_key, HEADING_NOTE_PATH.read_bytes()
    )
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                storage_key=storage_key,
                file_name="Headings.note",
                directory_id=0,
            )
        )
        await session.commit()
    hashing = PageHashingModule(file_service=client.app[FILE_SERVICE_KEY])
    assert await hashing.run(file_id, session_manager, user_id=user_id) is True
    return file_id


async def _title_image_paths(
    client: TestClient, auth_headers: dict[str, str], file_id: int
) -> list[str]:
    resp = await client.post(
        "/api/extended/file/note/metadata",
        json={"fileId": str(file_id)},
        headers=auth_headers,
    )
    assert resp.status == 200
    urls = [t["imageUrl"] for t in (await resp.json())["titles"]]
    return [URL(url).path_qs for url in urls]


async def test_note_metadata_route_returns_metadata(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    file_id = 8809
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=file_id,
                    user_id=test_user_id,
                    storage_key="k8809",
                    file_name="Daily.note",
                    directory_id=0,
                    is_active="Y",
                ),
                NoteMetadataDO(
                    user_id=test_user_id,
                    file_id=file_id,
                    native_file_id="F8809",
                    file_type="NOTE",
                    signature="SN_FILE_VER_20230015",
                    total_pages=1,
                    header_json='{"APPLY_EQUIPMENT": "N5"}',
                    footer_json="{}",
                ),
                NotePageMetadataDO(
                    user_id=test_user_id,
                    file_id=file_id,
                    page_index=0,
                    page_id="P1",
                    content_hash="h1",
                    page_style="style_white",
                    has_ink=True,
                    has_drawables=True,
                    page_json="{}",
                    keywords_json="[]",
                    titles_json="[]",
                    links_json="[]",
                ),
            ]
        )
        await session.commit()

    meta_vo = await extended_client.get_note_metadata(file_id)
    assert meta_vo.total_pages == 1
    assert meta_vo.equipment == "N5"


async def test_title_image_url_streams_signed_crop(
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    file_id = await _hash_heading_note(client, session_manager, test_user_id)
    paths = await _title_image_paths(client, auth_headers, file_id)
    assert [URL(p).path for p in paths] == [
        f"/api/oss/title/{file_id}/{md5}"
        for md5 in (
            "4f60eac0ba701b4983269a55649430ad",
            "b094a9f71c442cf2a0544d737603b0dc",
            "f14caee340e90ceab17cad156682ca9c",
            "63bcfe0053116378ededa5038ba7e389",
        )
    ]

    resp = await client.get(paths[0])

    assert resp.status == 200
    assert resp.content_type == "image/png"
    assert Image.open(io.BytesIO(await resp.read())).size == (356, 148)


async def test_title_image_rejects_unsigned_request(
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    file_id = await _hash_heading_note(client, session_manager, test_user_id)
    signed_path = (await _title_image_paths(client, auth_headers, file_id))[0]

    resp = await client.get(URL(signed_path).path)

    assert resp.status == 403
    assert await resp.json() == {
        "success": False,
        "errorCode": "E0072",
        "errorMsg": f"No signature found in URL: {URL(signed_path).path}",
    }


async def test_title_image_signature_is_bound_to_path(
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    file_id = await _hash_heading_note(client, session_manager, test_user_id)
    signed = URL((await _title_image_paths(client, auth_headers, file_id))[0])
    other_md5 = "b094a9f71c442cf2a0544d737603b0dc"

    resp = await client.get(
        signed.with_path(f"/api/oss/title/{file_id}/{other_md5}").path_qs
    )

    assert resp.status == 403
    assert (await resp.json())["success"] is False


async def test_title_image_not_found_for_deleted_signed_user(
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    assert client.app is not None
    file_id = await _hash_heading_note(client, session_manager, test_user_id)
    signed_path = (await _title_image_paths(client, auth_headers, file_id))[0]
    async with session_manager.session() as session:
        await session.execute(delete(UserDO).where(UserDO.id == test_user_id))
        await session.commit()

    resp = await client.get(signed_path)

    assert resp.status == 404
    assert await resp.json() == {
        "success": False,
        "errorMsg": "Title image not found",
    }
