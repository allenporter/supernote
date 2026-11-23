"""HTTP route tests for `supernote.server.components.search.http`."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.exceptions import ApiException, NotFoundException
from supernote.client.extended import ExtendedClient
from supernote.server.components.search import (
    SEARCH_SERVICE_KEY,
    SearchResult,
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


async def test_search_route_returns_results(
    client: TestClient,
    extended_client: ExtendedClient,
) -> None:
    """Verify POST /api/extended/search returns SearchResultVO payloads."""
    assert client.app is not None
    mock_results = [
        SearchResult(
            file_id=101,
            file_name="Work.note",
            page_index=1,
            page_id="P20260101000000",
            score=0.91,
            text_preview="Quarterly roadmap",
            date="2026-01-01",
        )
    ]
    with patch.object(
        client.app[SEARCH_SERVICE_KEY],
        "search_chunks",
        return_value=mock_results,
    ):
        response = await extended_client.search(query="roadmap", top_n=5)

    assert len(response.results) == 1
    assert response.results[0].file_id == 101
    assert response.results[0].file_name == "Work.note"
    assert response.results[0].score == pytest.approx(0.91)
    assert response.results[0].date == "2026-01-01"


async def test_search_route_invalid_dto_and_errors(
    client: TestClient,
    auth_headers: dict[str, str],
    extended_client: ExtendedClient,
    user_service: UserService,
) -> None:
    """Verify POST /api/extended/search handles 400, 404, and 500 error paths."""
    assert client.app is not None

    bad_resp = await client.post(
        "/api/extended/search",
        json={"invalid": "data"},
        headers=auth_headers,
    )
    assert bad_resp.status == 400

    with (
        patch.object(user_service, "get_user_id", return_value=None),
        pytest.raises(NotFoundException),
    ):
        await extended_client.search(query="test")

    with (
        patch.object(
            client.app[SEARCH_SERVICE_KEY],
            "search_chunks",
            side_effect=RuntimeError("Search crash"),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.search(query="test")
