import urllib.parse

import pytest

from supernote.client.client import Client
from tests.server.conftest import TEST_USERNAME, UserStorageHelper


async def test_empty_token(
    client: Client,
) -> None:
    result = await client.post("/api/user/query/token")
    data = await result.json()
    assert data == {
        "success": True,
        "token": None,  # Client expects this field always to be present
        "errorCode": None,
        "errorMsg": None,
    }
