"""Authentication utilities for both aiohttp and Starlette."""

from typing import Any, Protocol


class RequestLike(Protocol):
    """Protocol for objects that look like a request with headers, etc."""

    @property
    def headers(self) -> Any: ...


def get_token_from_request(request: Any) -> str | None:
    """Extract token from aiohttp or Starlette request.

    Checks `x-access-token` first, then `Authorization: Bearer <token>`.
    """
    if token := request.headers.get("x-access-token"):
        return str(token)

    auth_header = request.headers.get("Authorization") or request.headers.get(
        "authorization"
    )
    if isinstance(auth_header, str):
        scheme, _, credentials = auth_header.partition(" ")
        if scheme.lower() == "bearer" and credentials.strip():
            return credentials.strip()

    return None
