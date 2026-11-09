"""Authentication utilities for both aiohttp and Starlette."""

from typing import Any, Protocol


class RequestLike(Protocol):
    """Protocol for objects that look like a request with headers, etc."""

    @property
    def headers(self) -> Any: ...


def get_token_from_request(request: Any) -> str | None:
    """Extract token from aiohttp or Starlette request.

    Checks `x-access-token` and `Authorization: Bearer <token>`. If both headers
    are supplied with conflicting non-empty tokens, returns `None` so ambiguous
    dual-credential requests are rejected rather than silently shadowed.
    """
    raw_access_token = request.headers.get("x-access-token")
    access_token = str(raw_access_token).strip() if raw_access_token is not None else ""
    if raw_access_token is not None and not access_token:
        return None

    bearer_token = ""
    auth_header = request.headers.get("Authorization") or request.headers.get(
        "authorization"
    )
    if isinstance(auth_header, str):
        scheme, _, credentials = auth_header.partition(" ")
        if scheme.lower() == "bearer" and credentials.strip():
            bearer_token = credentials.strip()

    if access_token and bearer_token:
        return access_token if access_token == bearer_token else None

    return access_token or bearer_token or None
