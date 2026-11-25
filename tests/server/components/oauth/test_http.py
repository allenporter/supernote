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
from tests.fixtures.oauth import (
    TEST_CLIENT_ID,
    TEST_REDIRECT_URI,
    FakeDocumentFetcher,
    client_document,
)
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


@pytest.fixture
async def consent_session(user_service: UserService) -> dict[str, str]:
    """Headers for an interactive Web UI session."""
    await user_service.register(
        UserRegisterDTO(
            email="consent@example.com", password=hashlib.md5(b"pw").hexdigest()
        )
    )
    return {"x-access-token": await user_service.create_session("consent@example.com")}


@pytest.mark.parametrize(
    "redirect_uri",
    [None, TEST_REDIRECT_URI],
    ids=["registered-uri-when-omitted", "explicit-uri"],
)
async def test_login_bridge_client_describes_the_client(
    failing_clients: TestClient,
    consent_session: dict[str, str],
    redirect_uri: str | None,
) -> None:
    """The consent card learns the client's name, host and real redirect target."""
    params = {"client_id": TEST_CLIENT_ID}
    if redirect_uri:
        params["redirect_uri"] = redirect_uri
    resp = await failing_clients.get(
        "/login-bridge/client", params=params, headers=consent_session
    )
    assert resp.status == 200
    assert resp.headers["cache-control"] == "no-store"
    assert await resp.json() == {
        "client_name": "Example Client",
        "client_host": "client.example",
        "redirect_uri": TEST_REDIRECT_URI,
    }


async def test_login_bridge_client_names_an_indieauth_client_by_its_host(
    failing_clients: TestClient, consent_session: dict[str, str]
) -> None:
    """A client without a document has no name of its own; its host stands in."""
    resp = await failing_clients.get(
        "/login-bridge/client",
        params={"client_id": "http://192.168.1.10:8123/"},
        headers=consent_session,
    )
    assert await resp.json() == {
        "client_name": "192.168.1.10",
        "client_host": "192.168.1.10",
        "redirect_uri": "http://192.168.1.10:8123/",
    }


async def test_login_bridge_client_shows_an_idn_host_as_punycode(
    failing_clients: TestClient,
    consent_session: dict[str, str],
    client_metadata_documents: FakeDocumentFetcher,
) -> None:
    """A look-alike Unicode host is shown in the ASCII form that cannot impersonate."""
    client_id = "https://xn--80ak6aa92e.com/client.json"
    client_metadata_documents.documents[client_id] = client_document(
        client_id, "https://xn--80ak6aa92e.com/cb"
    )
    resp = await failing_clients.get(
        "/login-bridge/client", params={"client_id": client_id}, headers=consent_session
    )
    assert (await resp.json())["client_host"] == "xn--80ak6aa92e.com"


@pytest.mark.parametrize(
    ("params", "status", "body"),
    [
        ({}, 400, {"error": "invalid_request"}),
        (
            {"client_id": FAILING_CLIENTS["invalid"][0]},
            400,
            {
                "error": "invalid_client",
                "error_description": "The client's metadata document is missing or invalid.",
            },
        ),
        (
            {"client_id": FAILING_CLIENTS["unavailable"][0]},
            503,
            {
                "error": "temporarily_unavailable",
                "error_description": "The client's metadata document could not be fetched.",
            },
        ),
        (
            {"client_id": TEST_CLIENT_ID, "redirect_uri": "https://evil.example/cb"},
            400,
            {
                "error": "invalid_redirect_uri",
                "error_description": (
                    "Redirect URI is not registered for this client."
                ),
            },
        ),
    ],
    ids=["no-client-id", "invalid", "unavailable", "unregistered-redirect"],
)
async def test_login_bridge_client_refuses(
    failing_clients: TestClient,
    consent_session: dict[str, str],
    params: dict[str, str],
    status: int,
    body: dict[str, str],
) -> None:
    resp = await failing_clients.get(
        "/login-bridge/client", params=params, headers=consent_session
    )
    assert resp.status == status
    assert await resp.json() == body


@pytest.mark.parametrize(
    ("credential", "status", "body"),
    [
        (None, 401, {"error": "unauthorized"}),
        (
            "api_key",
            403,
            {
                "error": "forbidden",
                "error_description": "API keys cannot authorize OAuth clients",
            },
        ),
        (
            "oauth_token",
            403,
            {
                "error": "forbidden",
                "error_description": "OAuth tokens cannot authorize OAuth clients",
            },
        ),
    ],
)
async def test_login_bridge_client_requires_an_interactive_session(
    failing_clients: TestClient,
    user_service: UserService,
    credential: str | None,
    status: int,
    body: dict[str, str],
) -> None:
    """Fetching a client document on demand is for signed-in browser sessions only."""
    user = await user_service.register(
        UserRegisterDTO(
            email="keys@example.com", password=hashlib.md5(b"pw").hexdigest()
        )
    )
    headers = {}
    if credential == "api_key":
        api_key, _ = await user_service.create_api_key(user.id, "Headless CLI")
        headers["Authorization"] = f"Bearer {api_key}"
    elif credential == "oauth_token":
        token, _ = await user_service.create_oauth_grant(
            user.id, TEST_CLIENT_ID, [MCPScope.ALL]
        )
        headers["Authorization"] = f"Bearer {token}"
    resp = await failing_clients.get(
        "/login-bridge/client", params={"client_id": TEST_CLIENT_ID}, headers=headers
    )
    assert resp.status == status
    assert await resp.json() == body


@pytest.mark.parametrize(
    ("shown", "status"),
    [(TEST_REDIRECT_URI, 200), ("https://client.example/old-callback", 400)],
    ids=["unchanged", "changed"],
)
async def test_login_bridge_refuses_a_decision_on_a_changed_redirect(
    failing_clients: TestClient,
    consent_session: dict[str, str],
    shown: str,
    status: int,
) -> None:
    """The user approves the redirect they were shown, or nothing."""
    resp = await failing_clients.post(
        "/login-bridge",
        params={"client_id": TEST_CLIENT_ID, "code_challenge": "c" * 43},
        json={"decision": "approve", "redirect_uri": shown},
        headers=consent_session,
    )
    assert resp.status == status
    if status == 400:
        assert await resp.json() == {
            "error": "invalid_redirect_uri",
            "error_description": "The client's redirect URI changed. Reload to review it.",
        }


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
