"""Authentication request token extraction helpers for `aiohttp` and `Starlette`.

Provides `get_token_from_request`, which extracts the `x-access-token` header for session
verification in `supernote.server.app.jwt_auth_middleware` and `supernote.server.mcp.auth`.
"""

from typing import Any, Protocol


class RequestLike(Protocol):
    """Protocol for objects that look like a request with headers, etc."""

    @property
    def headers(self) -> Any: ...


def get_token_from_request(request: Any) -> str | None:
    """Extract token from aiohttp or Starlette request.

    Checks:
    1. x-access-token header
    """
    # Header check (case-insensitive usually handled by the framework objects)
    if token := request.headers.get("x-access-token"):
        return str(token)

    return None
