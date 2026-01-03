import urllib.parse

import pytest

from supernote.client.client import Client
from supernote.client.device import DeviceClient
from supernote.client.exceptions import ApiException


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
    import pytest

    from supernote.client.exceptions import ForbiddenException

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
