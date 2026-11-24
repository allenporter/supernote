"""HTTP platform tests for `supernote.server.components.oauth.http`."""

from __future__ import annotations

import hashlib

import pytest
from aiohttp.test_utils import TestClient
from pytest_aiohttp import AiohttpClient

from supernote.models.user import UserRegisterDTO
from supernote.server.components.oauth.client_metadata import (
    ClientMetadataUnavailableError,
)
from supernote.server.components.oauth.models import MCPScope
from supernote.server.core import ServerCore
from supernote.server.services.user import UserService
from tests.fixtures.oauth import TEST_REDIRECT_URI, FakeDocumentFetcher
from tests.server.components.conftest import LoadComponents


async def test_oauth_http_platform_serves_public_discovery_metadata(
    component_core: ServerCore,
    load_components: LoadComponents,
    aiohttp_client: AiohttpClient,
) -> None:
    await load_components("http", "oauth")
    client = await aiohttp_client(component_core.app)

    resp = await client.get("/.well-known/oauth-authorization-server")
    assert resp.status == 200
    metadata = await resp.json()
    assert metadata["issuer"].rstrip("/") == component_core.config.base_url.rstrip("/")
    assert "authorization_endpoint" in metadata
    assert "token_endpoint" in metadata


async def test_metadata_advertises_client_id_metadata_documents(
    component_core: ServerCore,
    load_components: LoadComponents,
    aiohttp_client: AiohttpClient,
) -> None:
    await load_components("http", "oauth")
    client = await aiohttp_client(component_core.app)
    resp = await client.get("/.well-known/oauth-authorization-server")
    assert resp.status == 200
    metadata = await resp.json()
    assert {
        key: metadata.get(key)
        for key in (
            "client_id_metadata_document_supported",
            "token_endpoint_auth_methods_supported",
            "revocation_endpoint_auth_methods_supported",
            "registration_endpoint",
            "authorization_response_iss_parameter_supported",
        )
    } == {
        "client_id_metadata_document_supported": True,
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
        "registration_endpoint": None,
        "authorization_response_iss_parameter_supported": None,
    }


FAILING_CLIENTS = {
    "invalid": ("https://client.example/invalid.json", 400),
    "unavailable": ("https://client.example/down.json", 503),
}


@pytest.fixture
async def failing_clients(
    component_core: ServerCore,
    load_components: LoadComponents,
    aiohttp_client: AiohttpClient,
    client_metadata_documents: FakeDocumentFetcher,
) -> TestClient:
    client_metadata_documents.documents[FAILING_CLIENTS["invalid"][0]] = {
        "client_id": "other"
    }
    client_metadata_documents.errors[FAILING_CLIENTS["unavailable"][0]] = (
        ClientMetadataUnavailableError("timed out")
    )
    await load_components("http", "oauth")
    return await aiohttp_client(component_core.app)


def _authorize_params(client_id: str) -> dict[str, str]:
    return {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": TEST_REDIRECT_URI,
        "code_challenge": "c" * 43,
        "code_challenge_method": "S256",
        "state": "st",
    }


@pytest.mark.parametrize("case", FAILING_CLIENTS)
async def test_authorize_never_redirects_a_failed_client(
    failing_clients: TestClient, case: str
) -> None:
    """Section 6.1: no redirect to the client; 503 when the document is unreachable."""
    client_id, status = FAILING_CLIENTS[case]
    resp = await failing_clients.get(
        "/authorize", params=_authorize_params(client_id), allow_redirects=False
    )
    assert resp.status == status
    assert "location" not in resp.headers


@pytest.mark.parametrize("case", FAILING_CLIENTS)
async def test_login_bridge_refuses_a_failed_client(
    failing_clients: TestClient, user_service: UserService, case: str
) -> None:
    client_id, status = FAILING_CLIENTS[case]
    await user_service.register(
        UserRegisterDTO(
            email="cimd@example.com", password=hashlib.md5(b"pw").hexdigest()
        )
    )
    session_jwt = await user_service.create_session("cimd@example.com")
    resp = await failing_clients.post(
        "/login-bridge",
        params=_authorize_params(client_id) | {"scope": MCPScope.ALL},
        headers={"x-access-token": session_jwt},
    )
    assert resp.status == status
    assert resp.headers["cache-control"] == "no-store"
    assert (await resp.json())["error"] == (
        "temporarily_unavailable" if status == 503 else "invalid_client"
    )


@pytest.mark.parametrize("case", FAILING_CLIENTS)
async def test_token_refuses_a_failed_client(
    failing_clients: TestClient, case: str
) -> None:
    client_id, status = FAILING_CLIENTS[case]
    resp = await failing_clients.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": "unused",
            "code_verifier": "v" * 50,
            "client_id": client_id,
            "redirect_uri": TEST_REDIRECT_URI,
        },
    )
    assert resp.status == (401 if status == 400 else 503)
    assert (await resp.json())["error"] == (
        "temporarily_unavailable" if status == 503 else "invalid_client"
    )


@pytest.mark.parametrize(
    ("client_id", "redirect_uri"),
    [
        ("http://192.168.1.10:8123/", "http://192.168.1.10:8123/auth/callback"),
        (
            "https://client.example/missing.json",
            "https://client.example/missing.json/callback",
        ),
    ],
    ids=["lan-http", "no-document"],
)
async def test_authorize_accepts_an_indieauth_client(
    failing_clients: TestClient,
    client_metadata_documents: FakeDocumentFetcher,
    client_id: str,
    redirect_uri: str,
) -> None:
    """Self-hosted and LAN clients without a metadata document still sign in."""
    params = _authorize_params(client_id) | {"redirect_uri": redirect_uri}
    resp = await failing_clients.get("/authorize", params=params, allow_redirects=False)
    assert resp.status == 302
    assert "/login-bridge?" in resp.headers["location"]
    if client_id.startswith("http://"):
        assert client_id not in client_metadata_documents.fetched
