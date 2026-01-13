from pathlib import Path

from supernote.client.device import DeviceClient


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
