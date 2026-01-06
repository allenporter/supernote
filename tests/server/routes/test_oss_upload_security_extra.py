import urllib.parse

from aiohttp import FormData

from supernote.client.client import Client
from supernote.client.device import DeviceClient


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
