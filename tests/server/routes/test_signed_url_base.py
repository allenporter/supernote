"""Tests for base-URL selection when signing upload/download URLs.

The signed URL routes prefer the explicitly configured base URL
(`SUPERNOTE_BASE_URL`) and fall back to the incoming request's origin when it
is unset. These tests mock a request and assert the returned URL is built from
the correct base.
"""

import json
from unittest.mock import AsyncMock

from aiohttp.test_utils import make_mocked_request

from supernote.models.file_common import FileUploadApplyLocalVO
from supernote.server.config import ServerConfig
from supernote.server.routes.file_web import handle_file_upload_apply

TEST_USER = "user@example.com"


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
