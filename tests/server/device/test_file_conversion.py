from pathlib import Path

from aiohttp.test_utils import TestClient
from sqlalchemy import delete

from supernote.client.device import DeviceClient
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.utils.paths import get_conversion_png_path, get_page_png_path


async def test_note_conversion_wrappers(
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
    # 1. Setup: Upload the test note
    with test_note_path.open("rb") as f:
        note_content = f.read()

    filename = "test_caching.note"
    upload_res = await device_client.upload_content(
        path=f"/{filename}", content=note_content, equipment_no="SN_TEST"
    )
    assert upload_res.id is not None
    file_id = int(upload_res.id)

    file_service = client.app["file_service"]

    # First conversion: this will download, parse, and save pages to USER_DATA_BUCKET
    png_pages_first = await device_client.get_note_png_pages(file_id)
    assert len(png_pages_first) > 0

    # Retrieve file info to get the storage_key
    user_email = "test@example.com"
    file_info = await file_service.get_file_info_by_id(user_email, file_id)
    assert file_info is not None
    storage_key = file_info.storage_key
    assert storage_key is not None

    # Deleting the source notebook from USER_DATA_BUCKET to prove caching:
    # If caching works, it should serve from USER_DATA_BUCKET and NOT attempt to download/parse the source file.
    await file_service.blob_storage.delete(USER_DATA_BUCKET, storage_key)

    # Second conversion: should succeed because files are cached in USER_DATA_BUCKET
    # (If caching fails, it will attempt to download the missing source file and throw FileNotFoundError)
    png_pages_second = await device_client.get_note_png_pages(file_id)
    assert len(png_pages_second) == len(png_pages_first)

    # Now let's test CACHE_BUCKET copying (Medium-path)
    # 1. Let's delete the files from USER_DATA_BUCKET's conversions directory
    user_id = await file_service.user_service.get_user_id(user_email)

    # Clean USER_DATA_BUCKET conversions
    for idx in range(len(png_pages_first)):
        png_storage_key = get_conversion_png_path(
            user_id=user_id,
            file_id=file_id,
            page_index=idx,
            file_md5=file_info.md5 or "nomd5",
        )
        await file_service.blob_storage.delete(USER_DATA_BUCKET, png_storage_key)

    # 2. Add records to NotePageContentDO and put dummy images in CACHE_BUCKET
    async with session_manager.session() as session:
        await session.execute(
            delete(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
        )
        for idx in range(len(png_pages_first)):
            page_id = f"page_id_mock_{idx}"
            content = NotePageContentDO(
                file_id=file_id,
                page_index=idx,
                page_id=page_id,
                content_hash=f"mock_hash_{idx}",
            )
            session.add(content)
            # Write mock PNG to CACHE_BUCKET
            cache_png_key = get_page_png_path(file_id, page_id)
            await file_service.blob_storage.put(
                CACHE_BUCKET, cache_png_key, b"mock_png_bytes"
            )
        await session.commit()

    # 3. Request conversion: should succeed by copying from CACHE_BUCKET to USER_DATA_BUCKET!
    png_pages_third = await device_client.get_note_png_pages(file_id)
    assert len(png_pages_third) == len(png_pages_first)

    # Let's verify that the files copied to USER_DATA_BUCKET actually contain our mock_png_bytes!
    for idx in range(len(png_pages_first)):
        png_storage_key = get_conversion_png_path(
            user_id=user_id,
            file_id=file_id,
            page_index=idx,
            file_md5=file_info.md5 or "nomd5",
        )
        # Read from USER_DATA_BUCKET
        chunks = []
        async for chunk in file_service.blob_storage.get(
            USER_DATA_BUCKET, png_storage_key
        ):
            chunks.append(chunk)
        assert b"".join(chunks) == b"mock_png_bytes"
