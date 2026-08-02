import hashlib
import urllib.parse

import pytest
from aiohttp import FormData

from supernote.client.client import Client
from supernote.client.device import DeviceClient
from supernote.client.exceptions import ApiException, ForbiddenException
from supernote.models.file_common import FileUploadApplyLocalVO
from supernote.models.system import FileChunkVO, UploadFileVO

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
