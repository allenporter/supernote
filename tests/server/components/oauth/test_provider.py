"""Tests for MCP OAuth authorization server and login-bridge boundaries."""

import base64
import hashlib
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from mcp.shared.auth import InvalidRedirectUriError
from pydantic import AnyUrl
from pytest_aiohttp import AiohttpClient

from supernote.models.user import UserRegisterDTO
from supernote.server.components.oauth.client_metadata import (
    ClientMetadataUnavailableError,
)
from supernote.server.components.oauth.models import (
    LoginBridgeDecision,
    LoginBridgeResponseVO,
    MCPScope,
    OAuthErrorResponseVO,
)
from supernote.server.components.oauth.provider import (
    UNAVAILABLE_MEMO_SIZE,
    IndieAuthClientInformation,
    SupernoteOAuthClientInformationFull,
    SupernoteOAuthProvider,
)
from supernote.server.core import ServerCore
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.user import UserService
from tests.fixtures.oauth import (
    TEST_CLIENT_ID,
    TEST_REDIRECT_URI,
    FakeDocumentFetcher,
    client_document,
)
from tests.server.components.conftest import LoadComponents

pytestmark = pytest.mark.usefixtures("client_metadata_documents")


def _pkce_s256(verifier: str) -> str:
    """Compute an RFC 7636 S256 PKCE code challenge."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def test_login_bridge_rejects_static_api_keys(
    component_core: ServerCore,
    load_components: LoadComponents,
    aiohttp_client: AiohttpClient,
    user_service: UserService,
) -> None:
    """Verify static Bearer API keys cannot mint OAuth authorization codes via /login-bridge."""
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user = await user_service.register(
        UserRegisterDTO(email="bridgeuser@example.com", password=pw_md5)
    )
    raw_api_key, _ = await user_service.create_api_key(user.id, "Headless CLI")
    session_jwt = await user_service.create_session("bridgeuser@example.com")

    await load_components("http", "oauth")
    client = await aiohttp_client(component_core.app)

    # Unauthenticated POST returns 401
    unauth_resp = await client.post("/login-bridge")
    assert unauth_resp.status == 401

    # Static API key via Authorization: Bearer or x-access-token is forbidden (403)
    bearer_resp = await client.post(
        "/login-bridge",
        headers={"Authorization": f"Bearer {raw_api_key}"},
    )
    assert bearer_resp.status == 403
    assert await bearer_resp.json() == {
        "error": "forbidden",
        "error_description": "API keys cannot authorize OAuth clients",
    }

    header_resp = await client.get(
        "/login-bridge",
        headers={"x-access-token": raw_api_key},
    )
    assert header_resp.status == 403

    # OAuth 2.1 access tokens are also forbidden from authorizing new OAuth clients (403)
    existing_oauth_token, _ = await user_service.create_oauth_grant(
        user.id, "client_1", ["supernote:all"]
    )
    oauth_resp = await client.post(
        "/login-bridge",
        headers={"Authorization": f"Bearer {existing_oauth_token}"},
    )
    assert oauth_resp.status == 403
    assert await oauth_resp.json() == {
        "error": "forbidden",
        "error_description": "OAuth tokens cannot authorize OAuth clients",
    }

    # Interactive session JWT passes auth check and reaches OAuth query validation (400)
    session_resp = await client.post(
        "/login-bridge",
        headers={"Authorization": f"Bearer {session_jwt}"},
    )
    assert session_resp.status == 400
    assert await session_resp.json() == {"error": "invalid_request"}


async def test_oauth_provider_tokens_follow_their_grant(
    component_core: ServerCore,
    load_components: LoadComponents,
    aiohttp_client: AiohttpClient,
    user_service: UserService,
) -> None:
    """Exchanged tokens verify with canonical actor, rotate on refresh, and stop working on revocation."""
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user = await user_service.register(
        UserRegisterDTO(email="granted@example.com", password=pw_md5)
    )
    session_jwt = await user_service.create_session("granted@example.com")

    await load_components("http", "oauth")
    client = await aiohttp_client(component_core.app)

    client_id = TEST_CLIENT_ID
    verifier = "v" * 50
    code_challenge = _pkce_s256(verifier)

    # Mint authorization code through /login-bridge
    bridge_resp = await client.post(
        "/login-bridge",
        params={
            "client_id": client_id,
            "code_challenge": code_challenge,
            "scope": MCPScope.ALL,
        },
        headers={"x-access-token": session_jwt},
    )
    assert bridge_resp.status == 200
    bridge_vo = LoginBridgeResponseVO.from_json(await bridge_resp.text())
    code_str = parse_qs(urlparse(bridge_vo.redirect_url).query)["code"][0]

    # Exchange authorization code + PKCE verifier at /token
    token_resp = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code_str,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert token_resp.status == 200
    issued = await token_resp.json()
    assert issued["refresh_token"] is not None
    access = await user_service.verify_token(issued["access_token"])
    assert access is not None
    assert (access.user_id, access.actor_id, access.scopes, access.actor) == (
        user.id,
        client_id,
        ["supernote:all"],
        f"oauth:{client_id}",
    )

    # Authorization codes are single-use
    replay_resp = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code_str,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert replay_resp.status == 400
    assert (await replay_resp.json())["error"] == "invalid_grant"

    # Refresh rotates the access token on the same grant and preserves the refresh token
    refresh_resp = await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": issued["refresh_token"],
            "client_id": client_id,
        },
    )
    assert refresh_resp.status == 200
    renewed = await refresh_resp.json()
    assert renewed["refresh_token"] == issued["refresh_token"]
    assert renewed["scope"] == "supernote:all"
    assert await user_service.verify_token(issued["access_token"]) is None
    assert await user_service.verify_token(renewed["access_token"]) is not None

    # Revoking a single access token invalidates only that access token while keeping the grant active
    revoke_access_resp = await client.post(
        "/revoke",
        data={
            "token": renewed["access_token"],
            "token_type_hint": "access_token",
            "client_id": client_id,
            "client_secret": "",
        },
    )
    assert revoke_access_resp.status == 200
    assert await user_service.verify_token(renewed["access_token"]) is None

    # Grant can still mint a fresh access token until the refresh token itself is revoked
    refresh_again_resp = await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": issued["refresh_token"],
            "client_id": client_id,
        },
    )
    assert refresh_again_resp.status == 200
    final_tokens = await refresh_again_resp.json()
    assert await user_service.verify_token(final_tokens["access_token"]) is not None

    # Revoking the refresh token ends the entire grant and invalidates its active access token
    revoke_refresh_resp = await client.post(
        "/revoke",
        data={
            "token": issued["refresh_token"],
            "token_type_hint": "refresh_token",
            "client_id": client_id,
            "client_secret": "",
        },
    )
    assert revoke_refresh_resp.status == 200
    assert await user_service.verify_token(final_tokens["access_token"]) is None

    # Revoking an already-invalidated access token is idempotent (RFC 7009)
    revoke_stale_resp = await client.post(
        "/revoke",
        data={
            "token": final_tokens["access_token"],
            "token_type_hint": "access_token",
            "client_id": client_id,
            "client_secret": "",
        },
    )
    assert revoke_stale_resp.status == 200

    revoked_refresh_resp = await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": issued["refresh_token"],
            "client_id": client_id,
        },
    )
    assert revoked_refresh_resp.status == 400
    assert (await revoked_refresh_resp.json())["error"] == "invalid_grant"


async def test_authorize_and_login_bridge_consent_invariants(
    component_core: ServerCore,
    load_components: LoadComponents,
    aiohttp_client: AiohttpClient,
    user_service: UserService,
    coordination_service: CoordinationService,
) -> None:
    """Verify /authorize omits None params, GET /login-bridge always redirects to UI, and POST validates scopes."""
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user = await user_service.register(
        UserRegisterDTO(email="consent@example.com", password=pw_md5)
    )
    session_jwt = await user_service.create_session("consent@example.com")

    await load_components("http", "oauth")
    client = await aiohttp_client(component_core.app)

    verifier = "c" * 50
    code_challenge = _pkce_s256(verifier)

    auth_resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": TEST_CLIENT_ID,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "scope": MCPScope.ALL,
        },
        allow_redirects=False,
    )
    assert auth_resp.status == 302
    bridge_url = auth_resp.headers["Location"]
    parsed_bridge = urlparse(bridge_url)
    bridge_qs = parse_qs(parsed_bridge.query)
    assert bridge_qs == {
        "client_id": [TEST_CLIENT_ID],
        "code_challenge": [code_challenge],
        "scope": [MCPScope.ALL],
    }

    bridge_path_qs = f"{parsed_bridge.path}?{parsed_bridge.query}"

    meta_resp = await client.get("/.well-known/oauth-authorization-server")
    assert meta_resp.status == 200
    issuer = (await meta_resp.json())["issuer"]

    # GET /login-bridge even with a valid session JWT redirects to SPA consent card
    # using an origin-relative return_to path so TLS-terminating reverse proxies work.
    get_resp = await client.get(
        bridge_path_qs,
        headers={"x-access-token": session_jwt},
        allow_redirects=False,
    )
    assert get_resp.status == 302
    assert get_resp.headers["cache-control"] == "no-store"
    location = get_resp.headers["location"]
    assert location.startswith("/#login?return_to=")
    decoded_return_to = unquote(location.removeprefix("/#login?return_to="))
    parsed_return_to = urlparse(decoded_return_to)
    assert not parsed_return_to.scheme
    assert not parsed_return_to.netloc
    assert parsed_return_to.path == parsed_bridge.path
    assert parse_qs(parsed_return_to.query) == bridge_qs

    # POST /login-bridge with decision=deny returns error=access_denied without minting a code
    deny_resp = await client.post(
        f"{bridge_path_qs}&state=deny-st",
        json={"decision": LoginBridgeDecision.DENY},
        headers={"x-access-token": session_jwt},
    )
    assert deny_resp.status == 200
    assert deny_resp.headers["cache-control"] == "no-store"
    deny_vo = LoginBridgeResponseVO.from_json(await deny_resp.text())
    deny_qs = parse_qs(urlparse(deny_vo.redirect_url).query)
    assert deny_qs == {
        "error": ["access_denied"],
        "state": ["deny-st"],
        "iss": [issuer],
    }

    # POST /login-bridge with unknown decision enum or malformed JSON returns 400 invalid_request
    for bad_body in (b'{"decision": "maybe"}', b"{not-json"):
        bad_body_resp = await client.post(
            bridge_path_qs,
            data=bad_body,
            headers={
                "x-access-token": session_jwt,
                "content-type": "application/json",
            },
        )
        assert bad_body_resp.status == 400
        assert bad_body_resp.headers["cache-control"] == "no-store"
        assert OAuthErrorResponseVO.from_json(
            await bad_body_resp.text()
        ) == OAuthErrorResponseVO(error="invalid_request")

    # POST /login-bridge with unsupported scope returns 400 invalid_scope
    bad_scope_resp = await client.post(
        "/login-bridge",
        params={
            "client_id": TEST_CLIENT_ID,
            "redirect_uri": TEST_REDIRECT_URI,
            "code_challenge": code_challenge,
            "scope": "unsupported:admin",
        },
        headers={"x-access-token": session_jwt},
    )
    assert bad_scope_resp.status == 400
    bad_scope_vo = OAuthErrorResponseVO.from_json(await bad_scope_resp.text())
    assert bad_scope_vo.error == "invalid_scope"
    assert bad_scope_vo.error_description == "Requested scope is not supported."

    # POST /login-bridge with omitted redirect_uri resolves single registered URI
    # and records redirect_uri_provided_explicitly=False naturally.
    ok_resp = await client.post(
        f"{bridge_path_qs}&resource=http%3A%2F%2Flocalhost%3A8081%2Fmcp",
        headers={"x-access-token": session_jwt},
    )
    assert ok_resp.status == 200
    assert ok_resp.headers["cache-control"] == "no-store"
    redirect_url = (await ok_resp.json())["redirect_url"]
    cb_qs = parse_qs(urlparse(redirect_url).query)
    assert "state" not in cb_qs
    assert cb_qs["iss"] == [issuer]
    code_str = cb_qs["code"][0]

    provider = SupernoteOAuthProvider(
        user_service=user_service,
        coordination_service=coordination_service,
        issuer_url=component_core.config.base_url,
    )
    client_info = await provider.get_client(TEST_CLIENT_ID)
    assert client_info is not None
    stored = await provider.load_authorization_code(client_info, code_str)
    assert stored is not None
    assert stored.user_id == user.id
    assert stored.scopes == [MCPScope.ALL]
    assert stored.redirect_uri_provided_explicitly is False
    assert stored.resource == "http://localhost:8081/mcp"


@pytest.mark.parametrize(
    "bad_client_id",
    [
        "not-a-url",
        "ftp://client.example/client.json",
        "obsidian://supernote-sync/app",
        "https://client.example:99999/client.json",
        "http://exa mple.example/",
        "http://xn--/",
        "https://user:pass@client.example/client.json",
        "https://client.example/client.json#frag",
        "https://client.example/app/../client.json",
        "https://client.example/app/./client.json",
        "https://client.example/app/%2e%2e/client.json",
        "https://client.example/app/%2E/client.json",
    ],
)
async def test_get_client_rejects_malformed_or_unsafe_client_ids(
    user_service: UserService,
    coordination_service: CoordinationService,
    bad_client_id: str,
) -> None:
    """Verify get_client rejects client IDs that break the Client Identifier URL rules."""
    provider = SupernoteOAuthProvider(
        user_service=user_service,
        coordination_service=coordination_service,
        issuer_url="http://localhost:8080",
    )
    assert await provider.get_client(bad_client_id) is None


@pytest.mark.parametrize(
    "client_id",
    [
        "http://homeassistant.local:8123/",
        "http://192.168.1.10:8123/",
        "https://home-assistant.example/",
        "https://client.example/missing.json",
    ],
    ids=["http-lan-name", "http-lan-address", "root-path", "no-document"],
)
async def test_get_client_falls_back_to_indieauth(
    user_service: UserService,
    coordination_service: CoordinationService,
    client_id: str,
) -> None:
    """A client ID that serves no metadata document is an IndieAuth-style client."""
    provider = SupernoteOAuthProvider(
        user_service,
        coordination_service,
        "https://notes.example",
        FakeDocumentFetcher(),
    )
    client = await provider.get_client(client_id)
    assert isinstance(client, IndieAuthClientInformation)
    assert [str(uri) for uri in client.redirect_uris or ()] == [client_id]


@pytest.mark.parametrize(
    ("redirect_uri", "allowed"),
    [
        ("https://home-assistant.example/auth/external/callback", True),
        ("https://home-assistant.example/", True),
        ("https://home-assistant.example.evil.example/cb", False),
        ("https://other.example/cb", False),
        ("javascript:alert(1)//", False),
    ],
)
def test_indieauth_redirects_share_the_client_origin(
    redirect_uri: str, allowed: bool
) -> None:
    client = IndieAuthClientInformation(
        client_id="https://home-assistant.example/",
        redirect_uris=[AnyUrl("https://home-assistant.example/")],
    )
    if allowed:
        assert client.validate_redirect_uri(AnyUrl(redirect_uri)) == AnyUrl(
            redirect_uri
        )
    else:
        with pytest.raises(InvalidRedirectUriError):
            client.validate_redirect_uri(AnyUrl(redirect_uri))


def test_indieauth_custom_scheme_blocks_traversal() -> None:
    """An omitted redirect resolves to the single URI; dot segments never pass."""
    single_client = IndieAuthClientInformation(
        client_id="obsidian://supernote-sync/app",
        redirect_uris=[AnyUrl("obsidian://supernote-sync/app")],
    )
    assert single_client.validate_redirect_uri(None) == AnyUrl(
        "obsidian://supernote-sync/app"
    )
    for invalid_uri in (
        "obsidian://supernote-sync/app/%2e%2e/evil",
        "obsidian://supernote-sync/app%5c..%5cevil",
        "obsidian://supernote-sync/app#frag",
        "obsidian://user:pass@supernote-sync/app",
    ):
        with pytest.raises(InvalidRedirectUriError):
            single_client.validate_redirect_uri(AnyUrl(invalid_uri))


def test_validate_redirect_uri_default_and_custom_scheme_traversal() -> None:
    """Verify validate_redirect_uri resolves omitted single URI and blocks dot-segment traversal."""
    single_client = SupernoteOAuthClientInformationFull(
        client_id="obsidian://supernote-sync/app",
        redirect_uris=[AnyUrl("obsidian://supernote-sync/app")],
    )
    assert single_client.validate_redirect_uri(None) == AnyUrl(
        "obsidian://supernote-sync/app"
    )

    empty_client = SupernoteOAuthClientInformationFull(
        client_id="obsidian://supernote-sync",
        redirect_uris=[],
    )
    with pytest.raises(InvalidRedirectUriError):
        empty_client.validate_redirect_uri(None)

    for invalid_uri in (
        "obsidian://supernote-sync/app/%2e%2e/evil",
        "obsidian://supernote-sync/app%5c..%5cevil",
        "obsidian://supernote-sync/app#frag",
        "obsidian://user:pass@supernote-sync/app",
    ):
        with pytest.raises(InvalidRedirectUriError):
            single_client.validate_redirect_uri(AnyUrl(invalid_uri))


async def test_get_client_builds_a_public_client(
    user_service: UserService, coordination_service: CoordinationService
) -> None:
    provider = SupernoteOAuthProvider(
        user_service,
        coordination_service,
        "https://notes.example",
        FakeDocumentFetcher(),
    )
    client = await provider.get_client(TEST_CLIENT_ID)
    assert client is not None
    assert client.model_dump(
        include={
            "client_id",
            "client_name",
            "client_secret",
            "redirect_uris",
            "grant_types",
            "token_endpoint_auth_method",
        },
        mode="json",
    ) == {
        "client_id": TEST_CLIENT_ID,
        "client_name": "Example Client",
        "client_secret": None,
        "redirect_uris": [TEST_REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_method": "none",
    }


async def test_unavailable_memo_is_bounded(
    user_service: UserService, coordination_service: CoordinationService
) -> None:
    fetcher = FakeDocumentFetcher()
    provider = SupernoteOAuthProvider(
        user_service, coordination_service, "https://notes.example", fetcher
    )
    for i in range(UNAVAILABLE_MEMO_SIZE + 1):
        client_id = f"https://down.example/{i}.json"
        fetcher.errors[client_id] = ClientMetadataUnavailableError("down")
        with pytest.raises(ClientMetadataUnavailableError):
            await provider.get_client(client_id)
    assert len(provider._unavailable_until) <= UNAVAILABLE_MEMO_SIZE


async def test_get_client_returns_none_for_an_invalid_document(
    user_service: UserService, coordination_service: CoordinationService
) -> None:
    fetcher = FakeDocumentFetcher()
    fetcher.documents[TEST_CLIENT_ID] = client_document(TEST_CLIENT_ID, "not a url")
    provider = SupernoteOAuthProvider(
        user_service, coordination_service, "https://notes.example", fetcher
    )
    assert await provider.get_client(TEST_CLIENT_ID) is None


async def test_get_client_does_not_refetch_an_unavailable_document_at_once(
    user_service: UserService, coordination_service: CoordinationService
) -> None:
    """The SDK's /authorize error path asks twice; the second ask must not fetch."""
    fetcher = FakeDocumentFetcher()
    fetcher.errors[TEST_CLIENT_ID] = ClientMetadataUnavailableError("timed out")
    provider = SupernoteOAuthProvider(
        user_service, coordination_service, "https://notes.example", fetcher
    )
    for _ in range(2):
        with pytest.raises(ClientMetadataUnavailableError):
            await provider.get_client(TEST_CLIENT_ID)
    assert fetcher.fetched == [TEST_CLIENT_ID]


LOOPBACK_CLIENT = SupernoteOAuthClientInformationFull(
    client_id=TEST_CLIENT_ID,
    redirect_uris=[
        AnyUrl("http://localhost/callback"),
        AnyUrl("http://127.0.0.1/callback"),
        AnyUrl("http://[::1]:8000/callback"),
        AnyUrl("https://client.example:8443/callback"),
    ],
)


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://localhost:49152/callback",
        "http://127.0.0.1/callback",
        "http://127.0.0.1:49152/callback",
        "http://[::1]:49152/callback",
        "https://client.example:8443/callback",
    ],
)
def test_loopback_redirect_port_may_vary(redirect_uri: str) -> None:
    """RFC 8252 7.3: a native client's loopback port is chosen at run time."""
    assert LOOPBACK_CLIENT.validate_redirect_uri(AnyUrl(redirect_uri)) == AnyUrl(
        redirect_uri
    )


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://localhost.client.example:49152/callback",
        "http://127.0.0.2:49152/callback",
        "http://127.0.0.1:49152/callback/extra",
        "http://127.0.0.1:49152/other",
        "https://127.0.0.1:49152/callback",
        "https://client.example:9443/callback",
        "https://client.example/callback",
    ],
)
def test_only_the_loopback_port_may_vary(redirect_uri: str) -> None:
    with pytest.raises(InvalidRedirectUriError):
        LOOPBACK_CLIENT.validate_redirect_uri(AnyUrl(redirect_uri))
