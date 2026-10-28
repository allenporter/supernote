import hashlib
import urllib.parse
from http import HTTPStatus
from pathlib import Path

import pytest
from aiohttp import FormData

from supernote.client.client import Client
from supernote.client.device import DeviceClient
from supernote.client.exceptions import ApiException, ForbiddenException
from supernote.models.file_common import FileUploadApplyLocalVO
from supernote.models.system import FileChunkVO, UploadFileVO
from supernote.server.config import ServerConfig
from supernote.server.utils.url_signer import UrlSigner

TEST_USER = "user@example.com"


async def test_oss_upload_simple(
    authenticated_client: Client,
    device_client: DeviceClient,
) -> None:
    path = "/oss_simple.txt"
    content = b"Simple Content"

    # Use client which now uses OSS under the hood
    await device_client.upload_content(path=path, content=content, equipment_no="TEST")

    # Download to verify
    downloaded = await device_client.download_content(path=path)
    assert downloaded == content


async def test_oss_chunked_upload(
    device_client: DeviceClient,
) -> None:
    path = "/oss_chunked.txt"
    content = b"Chunk " * 1000  # Enough to force chunks if chunk_size is small

    await device_client.upload_content(
        path=path, content=content, equipment_no="TEST", chunk_size=1024
    )

    downloaded = await device_client.download_content(path=path)
    assert downloaded == content


async def test_oss_download_range(
    device_client: DeviceClient,
) -> None:
    path = "/oss_range.txt"
    content = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    await device_client.upload_content(
        path="oss_range.txt", content=content, equipment_no="TEST"
    )

    # Test first 10 bytes
    part1 = await device_client.download_content(path=path, offset=0, length=10)
    assert part1 == b"0123456789"

    # Test offset 10, length 10
    part2 = await device_client.download_content(path=path, offset=10, length=10)
    assert part2 == b"ABCDEFGHIJ"

    # Test offset 20 to end
    part3 = await device_client.download_content(path=path, offset=20)
    assert part3 == b"KLMNOPQRSTUVWXYZ"

    # Test single byte
    part4 = await device_client.download_content(path=path, offset=0, length=1)
    assert part4 == b"0"


async def test_oss_download_range_reuses_signed_url(
    device_client: DeviceClient,
    client: Client,
) -> None:
    """Verify multiple Range requests can reuse a single signed download URL within its TTL."""
    content = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    upload_result = await device_client.upload_content(
        path="oss_range_reuse.txt", content=content, equipment_no="TEST"
    )
    assert upload_result.id

    download_info = await device_client.download_v3(int(upload_result.id), "TEST")
    assert download_info
    parsed = urllib.parse.urlparse(download_info.url)
    relative_url = f"{parsed.path}?{parsed.query}"

    resp1 = await client.get(relative_url, headers={"Range": "bytes=0-9"})
    assert resp1.status == 206
    assert await resp1.read() == b"0123456789"

    resp2 = await client.get(relative_url, headers={"Range": "bytes=10-19"})
    assert resp2.status == 206
    assert await resp2.read() == b"ABCDEFGHIJ"

    resp3 = await client.get(relative_url, headers={"Range": "bytes=20-"})
    assert resp3.status == 206
    assert await resp3.read() == b"KLMNOPQRSTUVWXYZ"


async def test_oss_invalid_signature(
    authenticated_client: Client,
    device_client: DeviceClient,
) -> None:
    # Get a valid URL then tamper with it
    path = "/oss_tamper.txt"
    await device_client.upload_content(path=path, content=b"content")

    query_res = await device_client.query_by_path(path, "WEB")
    assert query_res.entries_vo
    info = await device_client.download_v3(int(query_res.entries_vo.id), "WEB")
    assert info
    valid_url = info.url

    # Tamper signature
    parsed = urllib.parse.urlparse(valid_url)
    qs = urllib.parse.parse_qs(parsed.query)
    qs["signature"] = ["invalid_signature"]
    tampered_query = urllib.parse.urlencode(qs, doseq=True)
    tampered_url = parsed._replace(query=tampered_query).geturl()

    # Client should raise ForbiddenException (403)
    with pytest.raises(ForbiddenException):
        await authenticated_client.get(tampered_url)


async def test_oss_invalid_range_header(
    authenticated_client: Client,
    device_client: DeviceClient,
) -> None:
    # Upload a file first
    path = "/oss_bad_range.txt"
    await device_client.upload_content(path=path, content=b"content")

    query_res = await device_client.query_by_path(path, "WEB")
    assert query_res.entries_vo
    info = await device_client.download_v3(int(query_res.entries_vo.id), "WEB")
    assert info
    valid_url = info.url

    # Malformed Range header
    with pytest.raises(ApiException) as excinfo:
        await authenticated_client.get(valid_url, headers={"Range": "garbage"})
    assert "400" in str(excinfo.value)


@pytest.mark.parametrize("configured_base_url", ["https://notes.example.com/"])
async def test_upload_url_uses_configured_base_url(
    authenticated_client: Client,
) -> None:
    """A configured base URL is used regardless of the request's host."""
    payload = {"directoryId": 0, "fileName": "note.pdf", "size": 10, "md5": "deadbeef"}
    headers = {"Host": "internal-device.local:8080"}
    vo = await authenticated_client.post_json(
        "/api/file/upload/apply",
        FileUploadApplyLocalVO,
        json=payload,
        headers=headers,
    )

    assert vo.full_upload_url is not None
    assert vo.full_upload_url.startswith(
        "https://notes.example.com/api/oss/upload?path="
    )


async def test_upload_url_falls_back_to_request_origin(
    authenticated_client: Client,
) -> None:
    """With no configured base URL, the request's own origin (scheme + host) is used."""
    payload = {"directoryId": 0, "fileName": "note.pdf", "size": 10, "md5": "deadbeef"}
    headers = {"Host": "device.local:9000"}
    vo = await authenticated_client.post_json(
        "/api/file/upload/apply",
        FileUploadApplyLocalVO,
        json=payload,
        headers=headers,
    )

    assert vo.full_upload_url is not None
    assert vo.full_upload_url.startswith(
        "http://device.local:9000/api/oss/upload?path="
    )


async def test_oss_download_public_access_flow(
    authenticated_client: Client,
    device_client: DeviceClient,
    client: Client,
) -> None:
    """Verify entire flow of public OSS download with signature."""

    # Upload a file as authenticated user
    path = "/oss_security_test.txt"
    content = b"Security Test Content"
    upload_result = await device_client.upload_content(
        path=path, content=content, equipment_no="TEST"
    )
    assert upload_result.id
    file_id = int(upload_result.id)

    # Generate a signed url
    download_info = await device_client.download_v3(file_id, "TEST")
    assert download_info
    signed_url = download_info.url

    # 1. Access with authenticated client (Consumes Nonce 1)
    resp_bytes = await authenticated_client.get_content(signed_url)
    assert resp_bytes == content

    # 2. Access with UNauthenticated client
    # Cannot reuse signed_url because it was single-use and consumed above.
    # Generate a NEW signed URL for this step.
    download_info_2 = await device_client.download_v3(file_id, "TEST")
    signed_url_2 = download_info_2.url

    # Extract relative path from signed_url for test client
    parsed = urllib.parse.urlparse(signed_url_2)
    relative_url = f"{parsed.path}?{parsed.query}"

    resp_public = await client.get(relative_url, headers={})
    assert resp_public.status == 200
    assert await resp_public.read() == content


async def test_oss_upload_public_access_flow(
    device_client: DeviceClient,
    client: Client,
) -> None:
    """Verify entire flow of public OSS upload with signature."""

    filename = "oss_upload_security_test.txt"
    content = b"Upload Security Test Content"
    equipment_no = "TEST"

    # 1. Get upload URL (authenticated)
    # calls /api/file/3/files/upload/apply
    full_path = f"/{filename}"
    apply_vo = await device_client.upload_apply(
        file_name=filename, path=full_path, size=len(content), equipment_no=equipment_no
    )
    assert apply_vo.full_upload_url

    signed_url = apply_vo.full_upload_url

    # 2. Upload with UNauthenticated client using signed URL
    # Target behavior: Success (200 OK)

    # Extract relative path for client
    parsed = urllib.parse.urlparse(signed_url)
    relative_url = f"{parsed.path}?{parsed.query}"

    data = FormData()
    data.add_field("file", content, filename=filename)

    resp = await client.post(relative_url, data=data, headers={})
    assert resp.status == 200
    result = await resp.text()
    vo = UploadFileVO.from_json(result)
    assert vo.success
    assert vo.md5 == hashlib.md5(content).hexdigest()


async def test_oss_upload_part_public_access_flow(
    device_client: DeviceClient,
    client: Client,
) -> None:
    """Verify entire flow of public OSS upload part with signature."""

    filename = "oss_upload_part_security_test.txt"
    content = b"Part Security Test Content"
    equipment_no = "TEST"

    # 1. Get upload URL (authenticated)
    full_path = f"/{filename}"
    apply_vo = await device_client.upload_apply(
        file_name=filename, path=full_path, size=len(content), equipment_no=equipment_no
    )
    assert apply_vo.part_upload_url

    signed_url = apply_vo.part_upload_url

    # 2. Upload part with UNauthenticated client
    # Target behavior: Success (200 OK)

    parsed = urllib.parse.urlparse(signed_url)
    relative_url = f"{parsed.path}?{parsed.query}"

    data = FormData()
    data.add_field("file", content, filename=filename)

    # Append extra params expected by the endpoint
    upload_id = "test_upload_id"
    part_number = 1
    total_chunks = 1

    params = {
        "uploadId": upload_id,
        "partNumber": part_number,
        "totalChunks": total_chunks,
    }

    resp = await client.post(relative_url, data=data, params=params, headers={})
    assert resp.status == 200
    result = await resp.text()
    vo = FileChunkVO.from_json(result)
    assert vo.status == "success"
    assert vo.chunk_md5 == hashlib.md5(content).hexdigest()


async def test_oss_upload_part_consumption_logic(
    device_client: DeviceClient,
    client: Client,
) -> None:
    """Verify nonce consumption logic for chunked uploads.

    Expectation:
    - Nonce is NOT consumed for intermediate chunks.
    - Nonce IS consumed for the last chunk (part_number == total_chunks).
    """
    filename = "oss_consumption_test.txt"
    content = b"Consumption Test Content"
    equipment_no = "TEST"

    # 1. Get upload URL
    full_path = f"/{filename}"
    apply_vo = await device_client.upload_apply(
        file_name=filename, path=full_path, size=len(content), equipment_no=equipment_no
    )
    signed_url = apply_vo.part_upload_url
    assert signed_url and isinstance(signed_url, str)

    parsed = urllib.parse.urlparse(signed_url)
    relative_url = f"{parsed.path}?{parsed.query}"

    upload_id = "test_consumption_id"

    # 2. Upload Part 1 of 2 (Intermediate)
    # Should NOT consume nonce
    data1 = FormData()
    data1.add_field("file", b"part1", filename=filename)
    params1 = {
        "uploadId": upload_id,
        "partNumber": 1,
        "totalChunks": 2,
        "object_name": apply_vo.inner_name,
    }
    resp1 = await client.post(relative_url, data=data1, params=params1, headers={})
    assert resp1.status == 200

    # 3. Verify nonce is still valid by reusing URL for Part 1 again (simulating retry or parallel)
    # This proves it wasn't consumed
    data1_retry = FormData()
    data1_retry.add_field("file", b"part1", filename=filename)
    resp1_retry = await client.post(
        relative_url, data=data1_retry, params=params1, headers={}
    )
    assert resp1_retry.status == 200

    # 4. Upload Part 2 of 2 (Last Chunk)
    # Should CONSUME nonce
    data2 = FormData()
    data2.add_field("file", b"part2", filename=filename)
    params2 = {
        "uploadId": upload_id,
        "partNumber": 2,
        "totalChunks": 2,
        "object_name": apply_vo.inner_name,
    }
    resp2 = await client.post(relative_url, data=data2, params=params2, headers={})
    assert resp2.status == 200

    # 5. Verify nonce is now invalid
    data_fail = FormData()
    data_fail.add_field("file", b"msg", filename=filename)
    resp_fail = await client.post(
        relative_url, data=data_fail, params=params1, headers={}
    )
    assert resp_fail.status == 403
    text = await resp_fail.text()
    assert "Token invalid" in text


@pytest.mark.parametrize(
    ("file_name", "expected_mime", "can_inline"),
    [
        ("screenshot.png", "image/png", True),
        ("document.pdf", "application/pdf", True),
        ("notes.txt", "text/plain", True),
        ("data.json", "application/json", True),
        ("vector.svg", "image/svg+xml", False),
        ("page.html", "text/html", False),
        ("feed.xml", ("application/xml", "text/xml"), False),
        ("notebook.note", "application/octet-stream", False),
    ],
)
async def test_oss_download_content_type_and_disposition(
    device_client: DeviceClient,
    client: Client,
    file_name: str,
    expected_mime: str | tuple[str, ...],
    can_inline: bool,
) -> None:
    """Verify /api/oss/download sets Content-Type from filename and supports inline disposition for safe types."""
    content = b"Sample file content"
    upload_result = await device_client.upload_content(
        path=f"/{file_name}", content=content, equipment_no="TEST"
    )
    assert upload_result.id
    file_id = int(upload_result.id)

    download_info = await device_client.download_v3(file_id, "TEST")
    assert download_info
    parsed = urllib.parse.urlparse(download_info.url)
    relative_url = f"{parsed.path}?{parsed.query}"

    expected_mimes = (
        (expected_mime,) if isinstance(expected_mime, str) else expected_mime
    )
    expected_csp = (
        "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"
    )

    # Default download (without inline=1) always uses attachment
    resp_default = await client.get(relative_url, headers={})
    assert resp_default.status == 200
    assert resp_default.headers.get("Content-Type") in expected_mimes
    assert resp_default.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp_default.headers.get("Content-Security-Policy") == expected_csp
    assert (
        resp_default.headers.get("Content-Disposition")
        == f'attachment; filename="{file_name}"'
    )
    assert await resp_default.read() == content

    # Inline request (?inline=1) uses inline only for safe previewable types
    resp_inline = await client.get(f"{relative_url}&inline=1", headers={})
    assert resp_inline.status == 200
    assert resp_inline.headers.get("Content-Type") in expected_mimes
    assert resp_inline.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp_inline.headers.get("Content-Security-Policy") == expected_csp
    expected_disposition = "inline" if can_inline else "attachment"
    assert (
        resp_inline.headers.get("Content-Disposition")
        == f'{expected_disposition}; filename="{file_name}"'
    )
    assert await resp_inline.read() == content


async def test_oss_png_and_pdf_routes_require_matching_signed_path_and_ownership(
    device_client: DeviceClient,
    server_config: ServerConfig,
    test_note_path: Path,
    client: Client,
) -> None:
    """Verify /api/oss/png/{file_id}/{page_no} and /api/oss/pdf/{file_id} enforce signature and user ownership."""
    url_signer = UrlSigner(secret_key=server_config.auth.secret_key)

    note_content = test_note_path.read_bytes()
    upload_res = await device_client.upload_content(
        path="/oss_route_note.note", content=note_content, equipment_no="SN_TEST"
    )
    assert upload_res.id is not None
    file_id = int(upload_res.id)

    png_vo = await device_client.note_to_png(file_id)
    assert len(png_vo.png_page_vo_list) > 0
    first_png_url = png_vo.png_page_vo_list[0].url
    parsed_png = urllib.parse.urlparse(first_png_url)
    assert parsed_png.path == f"/api/oss/png/{file_id}/0"
    resp_png = await client.get(f"{parsed_png.path}?{parsed_png.query}", headers={})
    assert resp_png.status == HTTPStatus.OK
    assert (
        resp_png.headers.get("Content-Disposition")
        == 'attachment; filename="oss_route_note_page_0.png"'
    )

    pdf_vo = await device_client.note_to_pdf(file_id)
    assert pdf_vo.url is not None
    parsed_pdf = urllib.parse.urlparse(pdf_vo.url)
    assert parsed_pdf.path == f"/api/oss/pdf/{file_id}"
    resp_pdf = await client.get(f"{parsed_pdf.path}?{parsed_pdf.query}", headers={})
    assert resp_pdf.status == HTTPStatus.OK
    assert (
        resp_pdf.headers.get("Content-Disposition")
        == 'attachment; filename="oss_route_note.pdf"'
    )

    # A page selection is signed with its pages and served from its own blob
    pages_vo = await device_client.note_to_pdf(file_id, [0])
    assert pages_vo.url is not None
    parsed_pages = urllib.parse.urlparse(pages_vo.url)
    assert parsed_pages.path == f"/api/oss/pdf/{file_id}"
    assert urllib.parse.parse_qs(parsed_pages.query)["pages"] == ["0"]
    resp_pages = await client.get(
        f"{parsed_pages.path}?{parsed_pages.query}", headers={}
    )
    assert resp_pages.status == HTTPStatus.OK
    resp_full = await client.get(f"{parsed_pdf.path}?{parsed_pdf.query}", headers={})
    assert resp_full.status == HTTPStatus.OK

    bad_pages_url = await url_signer.sign(
        f"/api/oss/pdf/{file_id}?pages=first",
        user="test@example.com",
        single_use=False,
    )
    resp_bad_pages = await client.get(bad_pages_url, headers={})
    assert resp_bad_pages.status == HTTPStatus.BAD_REQUEST

    # Using a PNG signature on the PDF endpoint (or another page) is rejected
    tampered_path = f"/api/oss/pdf/{file_id}?{parsed_png.query}"
    resp_tampered = await client.get(tampered_path, headers={})
    assert resp_tampered.status == HTTPStatus.FORBIDDEN

    # A signed URL for a different user who does not own file_id returns 404
    other_user_url = await url_signer.sign(
        f"/api/oss/png/{file_id}/0",
        user="other@example.com",
        single_use=False,
    )
    resp_other = await client.get(other_user_url, headers={})
    assert resp_other.status == HTTPStatus.NOT_FOUND
