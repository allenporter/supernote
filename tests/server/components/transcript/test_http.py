"""HTTP route tests for `supernote.server.components.transcript.http`."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.exceptions import ApiException, NotFoundException
from supernote.client.extended import ExtendedClient
from supernote.server.components.transcript import (
    TRANSCRIPT_SERVICE_KEY,
    PageTranscript,
)
from supernote.server.services.user import UserService


@pytest.fixture
async def authenticated_client(
    client: TestClient,
    auth_headers: dict[str, str],
) -> Client:
    """Fixture for an authenticated Supernote HTTP Client."""
    token = auth_headers["x-access-token"]

    class TokenAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            return token

    return Client(client.session, auth=TokenAuth(), host=str(client.make_url("")))


@pytest.fixture
def extended_client(authenticated_client: Client) -> ExtendedClient:
    """Fixture for ExtendedClient."""
    return ExtendedClient(authenticated_client)


async def test_transcript_route_returns_pages_and_404_when_empty(
    client: TestClient,
    extended_client: ExtendedClient,
) -> None:
    """Verify POST /api/extended/transcript returns structured pages or 404 when empty."""
    assert client.app is not None
    mock_pages = [
        PageTranscript(
            page_index=0,
            page_id="P20260102000000",
            text="Meeting notes",
            date="2026-01-02",
        )
    ]
    with patch.object(
        client.app[TRANSCRIPT_SERVICE_KEY],
        "get_page_transcripts",
        return_value=mock_pages,
    ):
        response = await extended_client.get_transcript(file_id=101)

    assert len(response.pages) == 1
    assert response.pages[0].page_index == 0
    assert response.pages[0].text == "Meeting notes"

    with (
        patch.object(
            client.app[TRANSCRIPT_SERVICE_KEY],
            "get_page_transcripts",
            return_value=[],
        ),
        pytest.raises(NotFoundException),
    ):
        await extended_client.get_transcript(file_id=101)


async def test_transcript_route_invalid_dto_and_errors(
    client: TestClient,
    auth_headers: dict[str, str],
    extended_client: ExtendedClient,
    user_service: UserService,
) -> None:
    """Verify POST /api/extended/transcript handles 400, 404, and 500 error paths."""
    assert client.app is not None

    bad_resp = await client.post(
        "/api/extended/transcript",
        json={"invalid": "payload"},
        headers=auth_headers,
    )
    assert bad_resp.status == 400

    with (
        patch.object(user_service, "get_user_id", return_value=None),
        pytest.raises(NotFoundException),
    ):
        await extended_client.get_transcript(file_id=101)

    with (
        patch.object(
            client.app[TRANSCRIPT_SERVICE_KEY],
            "get_page_transcripts",
            side_effect=RuntimeError("Transcript crash"),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.get_transcript(file_id=101)
