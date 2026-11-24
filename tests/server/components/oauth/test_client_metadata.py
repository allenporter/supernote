"""Tests for Client ID Metadata Document fetching, validation and caching."""

import asyncio
import json
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractContextManager
from typing import Any
from unittest.mock import patch

import aiohttp
import pytest
from aiohttp import web
from aiohttp.client_reqrep import ConnectionKey
from aiohttp.resolver import DefaultResolver
from pytest_aiohttp import AiohttpServer

from supernote.server.components.oauth.client_metadata import (
    MAX_DOCUMENT_BYTES,
    ClientMetadata,
    ClientMetadataError,
    ClientMetadataUnavailableError,
    _cache_seconds,
    _is_public_address,
    _PublicAddressResolver,
    _read_document,
    fetch_client_metadata_document,
    is_client_id_url,
    resolve_client_metadata,
    validate_client_metadata,
)
from supernote.server.services.coordination import CoordinationService
from tests.fixtures.oauth import (
    TEST_CLIENT_ID,
    TEST_REDIRECT_URI,
    FakeDocumentFetcher,
    client_document,
)

ISSUER = "https://notes.example"
VALID = client_document(TEST_CLIENT_ID, TEST_REDIRECT_URI)
ReadPath = Callable[[str], Awaitable[tuple[str, str | None]]]


def _without(name: str) -> dict[str, Any]:
    return {k: v for k, v in VALID.items() if k != name}


def test_minimal_document_gets_sdk_defaults() -> None:
    """A document with only the required properties gets the SDK's grant defaults."""
    metadata = validate_client_metadata(
        TEST_CLIENT_ID, json.dumps(VALID | {"client_name": " Example "})
    )
    assert metadata == ClientMetadata(
        client_name="Example",
        redirect_uris=[TEST_REDIRECT_URI],
        grant_types=["authorization_code", "refresh_token"],
    )


@pytest.mark.parametrize(
    ("extra", "grant_types"),
    [
        ({"grant_types": ["authorization_code"]}, ["authorization_code"]),
        (
            {"grant_types": ["authorization_code", "refresh_token", "device_code"]},
            ["authorization_code", "refresh_token"],
        ),
        (
            {"token_endpoint_auth_methods_supported": ["private_key_jwt", "none"]},
            ["authorization_code", "refresh_token"],
        ),
        (
            {"logo_uri": "data:image/png;base64,AA", "application_type": "other"},
            ["authorization_code", "refresh_token"],
        ),
    ],
    ids=[
        "code-only",
        "unknown-grant-dropped",
        "extra-auth-method-ignored",
        "unread-fields-ignored",
    ],
)
def test_supported_values_are_intersected(
    extra: dict[str, Any], grant_types: list[str]
) -> None:
    """Unsupported values are dropped rather than treated as errors (sections 5, 6)."""
    metadata = validate_client_metadata(TEST_CLIENT_ID, json.dumps(VALID | extra))
    assert metadata.grant_types == grant_types


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://client.example/callback?x=1",
        "http://localhost/callback",
        "http://127.0.0.1:8000/callback",
        "http://[::1]/callback",
        "com.example.app:/callback",
        "obsidian://supernote-sync/callback",
    ],
)
def test_allowed_redirect_uris(redirect_uri: str) -> None:
    metadata = validate_client_metadata(
        TEST_CLIENT_ID, json.dumps(VALID | {"redirect_uris": [redirect_uri]})
    )
    assert metadata.redirect_uris == [redirect_uri]


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "javascript:fetch('//evil.example/')//",
        "JavaScript:alert(1)",
        "data:text/html,hi",
        "vbscript:msgbox",
        "file:///etc/passwd",
        "blob:https://client.example/id",
        "http://client.example/callback",
        "http://10.0.0.5/callback",
        "https://client.example/callback#frag",
        "https://claude.example@evil.example/callback",
        "ms-msdt:/id",
        "search-ms:query=x",
    ],
)
def test_unsafe_redirect_uris_are_rejected(redirect_uri: str) -> None:
    """A document can never send the browser to a script, a local file, or plain http."""
    document = VALID | {"redirect_uris": [TEST_REDIRECT_URI, redirect_uri]}
    with pytest.raises(ClientMetadataError):
        validate_client_metadata(TEST_CLIENT_ID, json.dumps(document))


@pytest.mark.parametrize(
    "document",
    [
        "not json",
        [TEST_CLIENT_ID],
        VALID | {"client_id": f"{TEST_CLIENT_ID}/"},
        VALID | {"client_id": "https://CLIENT.example/client.json"},
        _without("client_id"),
        VALID | {"client_secret": "s"},
        VALID | {"client_secret_expires_at": 0},
        _without("client_name"),
        VALID | {"client_name": " "},
        _without("redirect_uris"),
        VALID | {"redirect_uris": []},
        VALID | {"redirect_uris": TEST_REDIRECT_URI},
        VALID | {"token_endpoint_auth_method": "client_secret_basic"},
        VALID | {"token_endpoint_auth_method": "client_secret_jwt"},
        VALID | {"token_endpoint_auth_method": "private_key_jwt"},
        VALID
        | {"token_endpoint_auth_methods_supported": ["none", "client_secret_post"]},
        VALID | {"token_endpoint_auth_methods_supported": "none"},
        VALID | {"token_endpoint_auth_methods_supported": [{"a": 1}, "none"]},
        VALID
        | {
            "token_endpoint_auth_methods_supported": ["none"],
            "token_endpoint_auth_method": "client_secret_basic",
        },
        VALID | {"grant_types": ["refresh_token"]},
        VALID | {"response_types": ["token"]},
    ],
    ids=[
        "not-json",
        "not-object",
        "client-id-trailing-slash",
        "client-id-not-normalised",
        "client-id-missing",
        "client-secret",
        "client-secret-expires-at",
        "client-name-missing",
        "client-name-blank",
        "redirect-uris-missing",
        "redirect-uris-empty",
        "redirect-uris-not-list",
        "auth-method-secret-basic",
        "auth-method-secret-jwt",
        "auth-method-unsupported",
        "auth-methods-include-secret",
        "auth-methods-not-list",
        "auth-methods-not-strings",
        "auth-methods-with-secret-singular",
        "no-authorization-code-grant",
        "no-code-response-type",
    ],
)
def test_invalid_documents_are_rejected(document: Any) -> None:
    """Each section 4-6 rule, and the server's own policy, rejects a document."""
    text = document if isinstance(document, str) else json.dumps(document)
    with pytest.raises(ClientMetadataError) as err:
        validate_client_metadata(TEST_CLIENT_ID, text)
    assert not isinstance(err.value, ClientMetadataUnavailableError)


@pytest.mark.parametrize(
    ("client_id", "valid"),
    [
        (TEST_CLIENT_ID, True),
        ("https://client.example:8443/app?v=1", True),
        ("not-a-url", False),
        ("http://client.example/client.json", False),
        ("https://client.example", False),
        ("https://client.example/", False),
        ("https://client.example:0/client.json", False),
        ("https://client.example:99999/client.json", False),
        ("https://user:pass@client.example/client.json", False),
        ("https://client.example/client.json#frag", False),
        ("https://client.example/app/../client.json", False),
        ("https://client.example/app/./client.json", False),
        ("https://client.example/app/%2e%2e/client.json", False),
        ("https://client.example/app/%2E/client.json", False),
        ("https://client.example/app\\client.json", False),
        (f"https://client.example/{'a' * 2048}", False),
    ],
)
def test_client_id_url_rules(client_id: str, valid: bool) -> None:
    """Section 3: https, a real path, no userinfo, fragment or dot segments."""
    assert is_client_id_url(client_id) is valid


@pytest.mark.parametrize(
    ("cache_control", "expected"),
    [
        (None, 3600),
        ("public", 3600),
        ("max-age=0", 300),
        ("public, max-age=7200", 7200),
        ("max-age=9999999", 86400),
        ("no-store", None),
        ("no-cache, max-age=600", None),
    ],
)
def test_cache_seconds_are_bounded(
    cache_control: str | None, expected: int | None
) -> None:
    assert _cache_seconds(cache_control) == expected


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("93.184.216.34", True),
        ("2606:2800:220:1:248:1893:25c8:1946", True),
        ("127.0.0.1", False),
        ("10.0.0.5", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("::1", False),
        ("fe80::1%en0", False),
        ("::ffff:127.0.0.1", False),
        ("not-an-ip", False),
    ],
)
def test_only_public_addresses_are_fetched(address: str, public: bool) -> None:
    assert _is_public_address(address) is public


def _resolving_to(*addresses: str) -> AbstractContextManager[Any]:
    async def resolve(self: object, host: str, port: int, family: int) -> list[Any]:
        return [{"hostname": host, "host": a, "port": port} for a in addresses]

    return patch.object(DefaultResolver, "resolve", resolve)


async def test_resolver_keeps_only_public_addresses() -> None:
    resolver = _PublicAddressResolver()
    with _resolving_to("127.0.0.1", "93.184.216.34"):
        results = await resolver.resolve("client.example", 443)
    await resolver.close()
    assert [r["host"] for r in results] == ["93.184.216.34"]


async def test_hostname_resolving_to_private_addresses_is_refused() -> None:
    """The real fetcher connects only through the public-address resolver."""
    with _resolving_to("10.0.0.5"), pytest.raises(ClientMetadataError) as err:
        await fetch_client_metadata_document(TEST_CLIENT_ID)
    assert not isinstance(err.value, ClientMetadataUnavailableError)
    assert "public address" in str(err.value)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/client.json",
        "https://[::1]/client.json",
        "https://10.0.0.5:8443/client.json",
    ],
)
async def test_private_address_literals_are_never_fetched(url: str) -> None:
    with pytest.raises(ClientMetadataError) as err:
        await fetch_client_metadata_document(url)
    assert not isinstance(err.value, ClientMetadataUnavailableError)


async def _respond(body: bytes) -> web.Response:
    return web.Response(body=body, content_type="application/json")


@pytest.fixture
async def read_path(aiohttp_server: AiohttpServer) -> AsyncIterator[ReadPath]:
    """Read a path from a local server through `_read_document`."""
    text = json.dumps(VALID)

    async def ok(request: web.Request) -> web.Response:
        assert request.headers["Accept"] == "application/json"
        return web.Response(
            text=text,
            content_type="application/json",
            headers={"Cache-Control": "max-age=600"},
        )

    async def chunked(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse()
        response.enable_chunked_encoding()
        await response.prepare(request)
        for i in range(0, len(text), 7):
            await response.write(text[i : i + 7].encode())
        await response.write_eof()
        return response

    async def large(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse()
        await response.prepare(request)
        for _ in range(3):
            await response.write(b"x" * MAX_DOCUMENT_BYTES)
        await response.write_eof()
        return response

    async def redirect(request: web.Request) -> web.Response:
        raise web.HTTPFound("/ok")

    async def bom(request: web.Request) -> web.Response:
        return await _respond(b"\xef\xbb\xbf" + text.encode())

    async def utf16(request: web.Request) -> web.Response:
        return await _respond(text.encode("utf-16"))

    async def too_many(request: web.Request) -> web.Response:
        return web.Response(status=429)

    async def unavailable(request: web.Request) -> web.Response:
        return web.Response(status=503)

    app = web.Application()
    for path, handler in {
        "/ok": ok,
        "/chunked": chunked,
        "/large": large,
        "/redirect": redirect,
        "/bom": bom,
        "/utf16": utf16,
        "/429": too_many,
        "/503": unavailable,
    }.items():
        app.router.add_get(path, handler)
    server = await aiohttp_server(app)

    async with aiohttp.ClientSession() as session:

        async def read(path: str) -> tuple[str, str | None]:
            return await _read_document(session, str(server.make_url(path)))

        yield read


async def test_read_document_returns_text_and_cache_control(
    read_path: ReadPath,
) -> None:
    assert await read_path("/ok") == (json.dumps(VALID), "max-age=600")


async def test_read_document_reads_a_chunked_body_to_the_end(
    read_path: ReadPath,
) -> None:
    text, _ = await read_path("/chunked")
    assert json.loads(text) == VALID


@pytest.mark.parametrize(
    "path",
    ["/redirect", "/missing", "/large", "/utf16"],
    ids=["redirect-not-followed", "not-found", "too-large", "not-utf8"],
)
async def test_read_document_refuses(read_path: ReadPath, path: str) -> None:
    with pytest.raises(ClientMetadataError) as err:
        await read_path(path)
    assert not isinstance(err.value, ClientMetadataUnavailableError)


@pytest.mark.parametrize("path", ["/429", "/503"])
async def test_read_document_reports_server_trouble_as_unavailable(
    read_path: ReadPath, path: str
) -> None:
    with pytest.raises(ClientMetadataUnavailableError):
        await read_path(path)


async def test_read_document_reports_a_refused_connection_as_unavailable(
    aiohttp_server: AiohttpServer,
) -> None:
    server = await aiohttp_server(web.Application())
    url = str(server.make_url("/ok"))
    await server.close()
    async with aiohttp.ClientSession() as session:
        with pytest.raises(ClientMetadataUnavailableError):
            await _read_document(session, url)


async def test_read_document_refuses_an_untrusted_certificate() -> None:
    """A certificate failure is the host's fault, so retrying will not help."""
    key = ConnectionKey(
        "client.example", 443, True, True, None, None, None, "client.example"
    )
    error = aiohttp.ClientConnectorCertificateError(
        key, ssl.SSLCertVerificationError("self-signed certificate")
    )
    async with aiohttp.ClientSession() as session:
        with (
            patch.object(session, "get", side_effect=error),
            pytest.raises(ClientMetadataError, match="not trusted") as err,
        ):
            await _read_document(session, TEST_CLIENT_ID)
    assert not isinstance(err.value, ClientMetadataUnavailableError)


async def test_read_document_reports_a_timeout_as_unavailable(
    aiohttp_server: AiohttpServer,
) -> None:
    async def slow(request: web.Request) -> web.Response:
        await asyncio.sleep(1)
        return web.Response()

    app = web.Application()
    app.router.add_get("/slow", slow)
    server = await aiohttp_server(app)
    timeout = aiohttp.ClientTimeout(total=0.05)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        with pytest.raises(ClientMetadataUnavailableError):
            await _read_document(session, str(server.make_url("/slow")))


async def test_bom_document_fails_the_same_fresh_and_cached(
    read_path: ReadPath, coordination_service: CoordinationService
) -> None:
    """What is validated is what is cached, so the outcome cannot change on reuse."""
    text, _ = await read_path("/bom")
    fetcher = FakeDocumentFetcher()
    fetcher.documents[TEST_CLIENT_ID] = text
    for _ in range(2):
        with pytest.raises(ClientMetadataError):
            await resolve_client_metadata(
                coordination_service, fetcher, TEST_CLIENT_ID, ISSUER
            )
    assert fetcher.fetched == [TEST_CLIENT_ID, TEST_CLIENT_ID]


async def test_valid_document_is_fetched_once(
    coordination_service: CoordinationService,
) -> None:
    fetcher = FakeDocumentFetcher()
    first = await resolve_client_metadata(
        coordination_service, fetcher, TEST_CLIENT_ID, ISSUER
    )
    second = await resolve_client_metadata(
        coordination_service, fetcher, TEST_CLIENT_ID, ISSUER
    )
    assert first == second
    assert fetcher.fetched == [TEST_CLIENT_ID]


async def test_no_store_document_is_fetched_every_time(
    coordination_service: CoordinationService,
) -> None:
    fetcher = FakeDocumentFetcher()
    fetcher.cache_control = "no-store"
    for _ in range(2):
        await resolve_client_metadata(
            coordination_service, fetcher, TEST_CLIENT_ID, ISSUER
        )
    assert fetcher.fetched == [TEST_CLIENT_ID, TEST_CLIENT_ID]


async def test_invalid_document_is_never_cached(
    coordination_service: CoordinationService,
) -> None:
    fetcher = FakeDocumentFetcher()
    fetcher.documents[TEST_CLIENT_ID] = {"client_id": "other"}
    for _ in range(2):
        with pytest.raises(ClientMetadataError):
            await resolve_client_metadata(
                coordination_service, fetcher, TEST_CLIENT_ID, ISSUER
            )
    assert fetcher.fetched == [TEST_CLIENT_ID, TEST_CLIENT_ID]


@pytest.mark.parametrize(
    "client_id",
    ["http://client.example/client.json", f"{ISSUER}/client.json"],
    ids=["not-a-client-id-url", "issuer-origin"],
)
async def test_refused_client_ids_are_never_fetched(
    coordination_service: CoordinationService, client_id: str
) -> None:
    fetcher = FakeDocumentFetcher()
    with pytest.raises(ClientMetadataError):
        await resolve_client_metadata(coordination_service, fetcher, client_id, ISSUER)
    assert fetcher.fetched == []
