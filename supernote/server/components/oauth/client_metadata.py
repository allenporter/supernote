"""Client ID Metadata Documents (draft-ietf-oauth-client-id-metadata-document-03).

An OAuth client identifies itself with an HTTPS URL that serves a JSON document
describing it. The authorization server fetches that document, validates it, and
uses its `redirect_uris` for exact redirect matching. The validated fields are cached
in the coordination store; failures never are.
"""

import hashlib
import ipaddress
import json
import logging
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import aiohttp
import yarl
from aiohttp.abc import AbstractResolver, ResolveResult
from aiohttp.resolver import DefaultResolver
from mashumaro.mixins.json import DataClassJSONMixin
from mcp.shared.auth import OAuthClientMetadata
from pydantic import ValidationError

from supernote.server.services.coordination import CoordinationService

logger = logging.getLogger(__name__)

MAX_DOCUMENT_BYTES = 5 * 1024
MAX_CLIENT_ID_LENGTH = 2048
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=5)
DEFAULT_CACHE_SECONDS = 3600
MIN_CACHE_SECONDS = 300
MAX_CACHE_SECONDS = 86400

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
SUPPORTED_GRANT_TYPES = ("authorization_code", "refresh_token")
SHARED_SECRET_AUTH_METHODS = frozenset(
    {"client_secret_post", "client_secret_basic", "client_secret_jwt"}
)
# Schemes a browser would run or read locally rather than hand to a native app.
UNSAFE_REDIRECT_SCHEMES = frozenset(
    {
        "javascript",
        "data",
        "vbscript",
        "file",
        "blob",
        "about",
        "filesystem",
        "search-ms",
    }
)
# Fields the server reads; the rest of a document is never validated or used.
_READ_FIELDS = (
    "redirect_uris",
    "token_endpoint_auth_method",
    "grant_types",
    "response_types",
    "client_name",
)

DocumentFetcher = Callable[[str], Awaitable[tuple[str, str | None]]]
"""Fetches a document URL, returning its text and its Cache-Control header."""

_DOT_SEGMENT = re.compile(r"^\.{1,2}$")
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*$")
_MAX_AGE = re.compile(r"(?:^|,)\s*max-age\s*=\s*(\d+)", re.IGNORECASE)


class ClientMetadataError(Exception):
    """The client's metadata document is missing, invalid, or refused."""


class ClientMetadataUnavailableError(ClientMetadataError):
    """The client's metadata document could not be fetched right now."""


class _PrivateAddressError(OSError):
    """A host resolved only to special-use addresses."""


@dataclass(frozen=True)
class ClientMetadata(DataClassJSONMixin):
    """The parts of a validated document that the server acts on."""

    client_name: str
    """Human-readable name of the client."""

    redirect_uris: list[str]
    """Registered redirect URIs, matched exactly."""

    grant_types: list[str]
    """Grant types the client declared that this server supports."""


def is_client_id_url(raw: str) -> bool:
    """Whether a client ID follows the Client Identifier URL rules of section 3."""
    if len(raw) > MAX_CLIENT_ID_LENGTH or "#" in raw or "\\" in raw:
        return False
    try:
        url = yarl.URL(raw, encoded=True)
        return (
            url.scheme == "https"
            and bool(url.host)
            and bool(url.port)
            and url.user is None
            and url.password is None
            and url.path not in ("", "/")
            and not any(_DOT_SEGMENT.match(part) for part in url.path.split("/"))
        )
    except ValueError:
        return False


def _is_allowed_redirect_uri(uri: str) -> bool:
    """https, http on loopback (RFC 8252 7.3), or a native app's private-use scheme."""
    url = yarl.URL(uri, encoded=True)
    if url.fragment or "#" in uri or url.user is not None:
        return False
    scheme = url.scheme.lower()
    if scheme == "https":
        return bool(url.host)
    if scheme == "http":
        return url.raw_host in LOOPBACK_HOSTS
    return (
        bool(_SCHEME.match(scheme))
        and scheme not in UNSAFE_REDIRECT_SCHEMES
        and not scheme.startswith("ms-")
    )


def _is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global


class _PublicAddressResolver(AbstractResolver):
    """Resolves hosts to public addresses only, so the address checked is the one used."""

    def __init__(self) -> None:
        self._resolver = DefaultResolver()

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[ResolveResult]:
        results = await self._resolver.resolve(host, port, family)
        public = [result for result in results if _is_public_address(result["host"])]
        if not public:
            raise _PrivateAddressError(f"{host} does not resolve to a public address")
        return public

    async def close(self) -> None:
        await self._resolver.close()


def _cache_seconds(cache_control: str | None) -> int | None:
    """How long to keep a document, or None when the server forbids storing it."""
    if cache_control is None:
        return DEFAULT_CACHE_SECONDS
    directives = cache_control.lower()
    if "no-store" in directives or "no-cache" in directives:
        return None
    if match := _MAX_AGE.search(cache_control):
        return max(MIN_CACHE_SECONDS, min(int(match.group(1)), MAX_CACHE_SECONDS))
    return DEFAULT_CACHE_SECONDS


async def _read_document(
    session: aiohttp.ClientSession, url: str
) -> tuple[str, str | None]:
    """Fetch a document's text and Cache-Control header, applying the section 6 rules."""
    try:
        async with session.get(
            url,
            allow_redirects=False,
            headers={"Accept": "application/json"},
        ) as response:
            if response.status != 200:
                message = f"client metadata returned HTTP {response.status}"
                if response.status >= 500 or response.status == 429:
                    raise ClientMetadataUnavailableError(message)
                raise ClientMetadataError(message)
            body = bytearray()
            async for chunk in response.content.iter_chunked(MAX_DOCUMENT_BYTES):
                body += chunk
                if len(body) > MAX_DOCUMENT_BYTES:
                    raise ClientMetadataError("client metadata document is too large")
            cache_control = response.headers.get("Cache-Control")
    except aiohttp.ClientConnectorCertificateError as err:
        raise ClientMetadataError(
            f"client metadata host is not trusted: {err}"
        ) from err
    except aiohttp.ClientConnectorError as err:
        if isinstance(err.os_error, _PrivateAddressError):
            raise ClientMetadataError(str(err.os_error)) from err
        raise ClientMetadataUnavailableError(
            f"client metadata could not be fetched: {err}"
        ) from err
    except (aiohttp.ClientError, TimeoutError) as err:
        raise ClientMetadataUnavailableError(
            f"client metadata could not be fetched: {err}"
        ) from err
    try:
        return body.decode("utf-8"), cache_control
    except UnicodeDecodeError as err:
        raise ClientMetadataError("client metadata is not UTF-8") from err


async def fetch_client_metadata_document(url: str) -> tuple[str, str | None]:
    """Fetch a Client ID Metadata Document from a public HTTPS address."""
    host = (yarl.URL(url, encoded=True).host or "").strip("[]")
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        pass
    else:
        if not _is_public_address(host):
            raise ClientMetadataError("client_id must not point at a private address")
    connector = aiohttp.TCPConnector(resolver=_PublicAddressResolver())
    async with aiohttp.ClientSession(
        connector=connector, timeout=FETCH_TIMEOUT, cookie_jar=aiohttp.DummyCookieJar()
    ) as session:
        return await _read_document(session, url)


def validate_client_metadata(client_id: str, text: str) -> ClientMetadata:
    """Validate a document against sections 4 to 6 and the server's own policy."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as err:
        raise ClientMetadataError("client metadata is not valid JSON") from err
    if not isinstance(document, dict):
        raise ClientMetadataError("client metadata must be a JSON object")
    if document.get("client_id") != client_id:
        raise ClientMetadataError("client metadata client_id does not match its URL")
    if "client_secret" in document or "client_secret_expires_at" in document:
        raise ClientMetadataError("client metadata must not contain a client secret")

    try:
        metadata = OAuthClientMetadata.model_validate(
            {key: document[key] for key in _READ_FIELDS if key in document}
        )
    except ValidationError as err:
        raise ClientMetadataError(f"client metadata is malformed: {err}") from err
    auth_methods = document.get("token_endpoint_auth_methods_supported", [])
    if not isinstance(auth_methods, list) or not all(
        isinstance(method, str) for method in auth_methods
    ):
        raise ClientMetadataError("token_endpoint_auth_methods_supported is malformed")
    if metadata.token_endpoint_auth_method or not auth_methods:
        auth_methods = [*auth_methods, metadata.token_endpoint_auth_method or "none"]
    if SHARED_SECRET_AUTH_METHODS.intersection(auth_methods):
        raise ClientMetadataError("client metadata must not use shared-secret auth")
    if "none" not in auth_methods:
        raise ClientMetadataError("client metadata names no supported auth method")

    client_name = (metadata.client_name or "").strip()
    if not client_name:
        raise ClientMetadataError("client metadata must contain client_name")
    redirect_uris = [str(uri) for uri in metadata.redirect_uris or ()]
    if not redirect_uris or not all(
        _is_allowed_redirect_uri(uri) for uri in redirect_uris
    ):
        raise ClientMetadataError("client metadata has a disallowed redirect URI")
    grant_types = [g for g in SUPPORTED_GRANT_TYPES if g in metadata.grant_types]
    if "authorization_code" not in grant_types or "code" not in metadata.response_types:
        raise ClientMetadataError("client metadata has no supported grant type")

    return ClientMetadata(
        client_name=client_name, redirect_uris=redirect_uris, grant_types=grant_types
    )


async def resolve_client_metadata(
    coordination: CoordinationService,
    fetch_document: DocumentFetcher,
    client_id: str,
    issuer_url: str,
) -> ClientMetadata:
    """Return a client's validated metadata from the cache, fetching it on a miss."""
    if not is_client_id_url(client_id):
        raise ClientMetadataError("client_id is not a valid Client Identifier URL")
    if yarl.URL(client_id).origin() == yarl.URL(issuer_url).origin():
        raise ClientMetadataError("client_id must not be on this server's origin")
    digest = hashlib.sha256(client_id.encode()).hexdigest()
    cache_key = f"oauth:client_metadata:v1:{digest}"
    if cached := await coordination.get_value(cache_key):
        return ClientMetadata.from_json(cached)

    text, cache_control = await fetch_document(client_id)
    metadata = validate_client_metadata(client_id, text)
    if (ttl := _cache_seconds(cache_control)) is not None:
        await coordination.set_value(cache_key, json.dumps(metadata.to_dict()), ttl=ttl)
    return metadata
