import json
import urllib.parse
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import make_mocked_request

from supernote.client.client import Client
from supernote.client.device import DeviceClient
from supernote.client.exceptions import ApiException
from supernote.models.file_common import FileUploadApplyLocalVO
from supernote.server.config import ServerConfig
from supernote.server.routes.file_web import handle_file_upload_apply

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


# ---------------------------------------------------------------------------
# Base-URL selection when signing upload/download URLs.
#
# The signed URL routes prefer the explicitly configured base URL
# (``SUPERNOTE_BASE_URL``) and fall back to the incoming request's origin when
# it is unset. These tests mock a request and assert the returned URL is built
# from the correct base.
# ---------------------------------------------------------------------------


def _make_request(config: ServerConfig, *, host: str, scheme: str = "http"):
    """Build a mocked upload-apply request backed by ``config``."""
    url_signer = AsyncMock()
    # The signer returns the path with a signature appended.
    url_signer.sign.return_value = "/api/oss/upload?path=inner.pdf&signature=abc"

    app = {"url_signer": url_signer, "config": config}
    headers = {"Host": host}
    if scheme == "https":
        headers["X-Forwarded-Proto"] = "https"

    payload = {"fileName": "note.pdf", "size": 10, "md5": "deadbeef"}
    request = make_mocked_request(
        "POST",
        "/api/file/upload/apply",
        headers=headers,
        app=app,
    )
    request["user"] = TEST_USER
    # Provide the JSON body the handler reads.
    request.json = AsyncMock(return_value=payload)  # type: ignore[method-assign]
    return request


async def _get_full_url(request) -> str:
    response = await handle_file_upload_apply(request)
    vo = FileUploadApplyLocalVO.from_dict(json.loads(response.body))
    assert vo.full_upload_url is not None
    return vo.full_upload_url


async def test_upload_url_uses_configured_base_url() -> None:
    """A configured base URL is used regardless of the request's host."""
    config = ServerConfig(_base_url="https://notes.example.com/")
    request = _make_request(config, host="internal-device.local:8080")

    full_url = await _get_full_url(request)

    assert full_url == (
        "https://notes.example.com/api/oss/upload?path=inner.pdf&signature=abc"
    )


async def test_upload_url_falls_back_to_request_origin() -> None:
    """With no configured base URL, the request's own origin is used."""
    config = ServerConfig()
    assert config.configured_base_url is None
    request = _make_request(config, host="device.local:9000")

    full_url = await _get_full_url(request)

    assert full_url == (
        "http://device.local:9000/api/oss/upload?path=inner.pdf&signature=abc"
    )
