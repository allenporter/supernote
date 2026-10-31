"""HMAC-SHA256 JWT URL signer and verifier (`UrlSigner`) for `/api/oss/*` transfers.

Appends and validates time-limited, user-bound `&signature=<jwt>` query parameters on
local object storage upload and download URLs (`supernote.server.routes.oss`). Supports
single-use nonce consumption backed by `supernote.server.services.coordination.CoordinationService`
as well as reusable URLs (`consume=False`) for multi-chunk uploads and byte-range downloads.

Usage example:

```python
signer = UrlSigner(secret_key="my-secret")

# Generate a signed URL (default 15 mins expiry)
full_url = await signer.sign("/api/oss/download?id=123")

# Verify the signature
payload = await signer.verify("/api/oss/download", signature_token)
```
"""

import datetime
import logging
import time
import urllib.parse
import uuid
from typing import Any

import jwt
from aiohttp import web

from supernote.server.exceptions import InvalidSignature, SignerError
from supernote.server.services.coordination import CoordinationService

logger = logging.getLogger(__name__)

DEFAULT_EXPIRATION = datetime.timedelta(minutes=15)


class UrlSigner:
    """Sign and verify URLs using HMAC-SHA256 (via JWT)."""

    def __init__(
        self,
        secret_key: str,
        coordination_service: CoordinationService | None = None,
    ) -> None:
        """Initialize the signer with a secret key."""
        self.secret_key = secret_key
        self.algorithm = "HS256"
        self._coordination_service = coordination_service

    async def sign(
        self,
        path: str,
        user: str | None = None,
        expiration: datetime.timedelta = DEFAULT_EXPIRATION,
        single_use: bool = True,
    ) -> str:
        """Sign a path and return the full signed URL.

        Args:
            path: The path to sign (e.g. /api/file/download/data?path=...)
            user: The user email to embed in the signature.
            expiration: Expiration duration (timedelta).
            single_use: Whether to register a single-use nonce in CoordinationService.

        Returns:
            The full signed URL with the signature query parameter appended.
        """
        if not path.startswith("/"):
            raise ValueError("Path must start with '/'")
        if "#" in path:
            raise ValueError("URL fragments (anchors) are not supported")

        if expiration < datetime.timedelta(seconds=0):
            raise ValueError("Expiration must be non-negative")

        now = int(time.time())
        now_ms = int(time.time() * 1000)

        exp = now + int(expiration.total_seconds())
        nonce = uuid.uuid4().hex

        # whitelist logic: store nonce before issuing token
        if self._coordination_service and single_use:
            # Key format: nonce:{user}:{nonce} for easier namespacing/debug
            # Fallback to 'anon' if no user provided
            user_key_part = user if user else "anon"
            key = f"nonce:{user_key_part}:{nonce}"

            # Store with TTL matching expiration + buffer (e.g. 1m) to ensure it lives long enough
            # We use "1" as value indicating "valid/issed"
            ttl = int(expiration.total_seconds()) + 60
            await self._coordination_service.set_value(key, "1", ttl=ttl)

        payload: dict[str, Any] = {
            "path": path,
            "exp": exp,
            "nonce": nonce,
            "iat": now,
            "timestamp": now_ms,
        }
        if not single_use:
            payload["single_use"] = False
        if user:
            payload["user"] = user

        try:
            token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        except jwt.PyJWTError as err:
            raise SignerError(f"Failed to encode signature: {err}") from err

        # Check if query params exist
        separator = "&" if "?" in path else "?"
        return f"{path}{separator}timestamp={now_ms}&nonce={nonce}&signature={token}"

    async def verify(self, signed_url: str, consume: bool = True) -> dict[str, Any]:
        """Verify the signature embedded in the URL.

        Args:
            signed_url: The full path + query string containing the signature.
            consume: Whether to consume the nonce (single-use). Default True.

        Returns:
            The decoded payload if valid.
        """
        if not signed_url.startswith("/"):
            raise ValueError("Path must start with '/'")

        # Parse URL and extract signature
        parsed = urllib.parse.urlparse(signed_url)
        query_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        if not (signatures := query_params.get("signature")) or len(signatures) != 1:
            raise InvalidSignature(f"No signature found in URL: {signed_url}")

        signature = signatures[0]
        try:
            payload = jwt.decode(
                signature, self.secret_key, algorithms=[self.algorithm]
            )
        except jwt.ExpiredSignatureError as err:
            raise InvalidSignature(f"Signature expired: {signed_url}") from err
        except jwt.InvalidTokenError as err:
            raise InvalidSignature(f"Invalid signature: {signed_url}") from err
        except jwt.PyJWTError as err:
            raise InvalidSignature(f"Error decoding signature: {err}") from err

        if not isinstance(payload, dict):
            raise InvalidSignature(f"Invalid payload type: {type(payload)}")

        if not (expected_path := payload.get("path")) or not isinstance(
            expected_path, str
        ):
            raise InvalidSignature(f"No path found in payload: {payload}")

        expected_parsed = urllib.parse.urlparse(expected_path)
        if parsed.path != expected_parsed.path:
            raise InvalidSignature(
                f"Signed path mismatch: expected path '{expected_parsed.path}', got '{parsed.path}'"
            )

        expected_query = urllib.parse.parse_qs(
            expected_parsed.query, keep_blank_values=True
        )
        for key, expected_values in expected_query.items():
            if query_params.get(key) != expected_values:
                raise InvalidSignature(f"Signed query parameter mismatch for '{key}'")

        # Verify timestamp if present in payload
        if "timestamp" in payload:
            ts_param = query_params.get("timestamp")
            if not ts_param or len(ts_param) != 1:
                raise InvalidSignature("Timestamp missing from URL")
            if str(payload["timestamp"]) != ts_param[0]:
                raise InvalidSignature("Timestamp mismatch")

        nonce = payload.get("nonce")
        if "nonce" in query_params:
            nonce_param = query_params["nonce"]
            if len(nonce_param) != 1 or str(nonce) != nonce_param[0]:
                raise InvalidSignature("Nonce mismatch")

        # Consume or check nonce in CoordinationService after URL integrity checks pass
        user = payload.get("user")
        is_single_use = payload.get("single_use", True)
        if self._coordination_service and nonce and is_single_use:
            user_key_part = user if user else "anon"
            key = f"nonce:{user_key_part}:{nonce}"

            if consume:
                val = await self._coordination_service.pop_value(key)
                if not val:
                    raise InvalidSignature(
                        f"Token invalid or already used (nonce: {nonce})"
                    )
            else:
                val = await self._coordination_service.get_value(key)
                if not val:
                    raise InvalidSignature(f"Token invalid or expired (nonce: {nonce})")

        return payload

    @staticmethod
    def extract_signature(url: str) -> str | None:
        """Extract the signature from a signed URL."""
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        return qs.get("signature", [None])[0]

    @staticmethod
    def extract_timestamp(url: str) -> str | None:
        """Extract the timestamp from a signed URL."""
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        return qs.get("timestamp", [None])[0]


def get_request_base_url(request: web.Request) -> str:
    """Get the base URL for generating absolute URLs in request handlers.

    Prefers `ServerConfig.configured_base_url` when set (`SUPERNOTE_BASE_URL`),
    falling back to `f"{request.scheme}://{request.host}"` derived from the request.
    """
    config = request.app.get("config")
    if config and config.configured_base_url:
        return config.configured_base_url
    return f"{request.scheme}://{request.host}"
