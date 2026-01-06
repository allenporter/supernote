import hashlib
import urllib.parse

from aiohttp import FormData

from supernote.client.client import Client
from supernote.client.device import DeviceClient
from supernote.models.system import FileChunkVO, UploadFileVO


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
