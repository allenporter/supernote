"""OAuth clients that publish Client ID Metadata Documents, served without a network."""

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest

from supernote.server.components.oauth.client_metadata import (
    ClientMetadataError,
    NotClientMetadataDocumentError,
)

TEST_CLIENT_ID = "https://client.example/client.json"
TEST_REDIRECT_URI = "https://client.example/callback"
OTHER_CLIENT_ID = "https://other.example/client.json"
OTHER_REDIRECT_URI = "https://other.example/callback"


def client_document(client_id: str, *redirect_uris: str) -> dict[str, Any]:
    """A minimal valid document for a public client."""
    return {
        "client_id": client_id,
        "client_name": "Example Client",
        "redirect_uris": list(redirect_uris),
    }


class FakeDocumentFetcher:
    """Serves documents by URL; a missing URL serves no document (HTTP 404)."""

    def __init__(self) -> None:
        self.documents: dict[str, Any] = {
            TEST_CLIENT_ID: client_document(TEST_CLIENT_ID, TEST_REDIRECT_URI),
            OTHER_CLIENT_ID: client_document(OTHER_CLIENT_ID, OTHER_REDIRECT_URI),
        }
        self.errors: dict[str, ClientMetadataError] = {}
        self.cache_control: str | None = None
        self.fetched: list[str] = []

    async def __call__(self, url: str) -> tuple[str, str | None]:
        self.fetched.append(url)
        if url in self.errors:
            raise self.errors[url]
        if url not in self.documents:
            raise NotClientMetadataDocumentError("HTTP 404 text/html")
        document = self.documents[url]
        text = document if isinstance(document, str) else json.dumps(document)
        return text, self.cache_control


@pytest.fixture
def client_metadata_documents() -> Iterator[FakeDocumentFetcher]:
    """Serve client documents to every OAuth provider the server builds."""
    fetcher = FakeDocumentFetcher()
    with patch(
        "supernote.server.components.oauth.provider.fetch_client_metadata_document",
        fetcher,
    ):
        yield fetcher
