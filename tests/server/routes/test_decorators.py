"""Tests for route handler decorators and sensitive endpoint authorization invariants."""

from pathlib import Path

from aiohttp import web

from supernote.server.app import create_app
from supernote.server.config import ServerConfig
from supernote.server.routes.admin import require_admin
from supernote.server.routes.decorators import interactive_session_only, public_route


def test_route_decorators_set_handler_attributes() -> None:
    """Verify @public_route, @interactive_session_only, and @require_admin preserve attributes."""

    @public_route
    async def open_handler(request: web.Request) -> web.StreamResponse:
        return web.Response(text="ok")

    @interactive_session_only
    async def session_handler(request: web.Request) -> web.StreamResponse:
        return web.Response(text="ok")

    @require_admin
    async def admin_handler(request: web.Request) -> web.Response:
        return web.Response(text="admin")

    assert getattr(open_handler, "is_public", False) is True
    assert getattr(open_handler, "interactive_session_only", False) is False

    assert getattr(session_handler, "interactive_session_only", False) is True
    assert getattr(session_handler, "is_public", False) is False

    assert getattr(admin_handler, "interactive_session_only", False) is True
    assert admin_handler.__name__ == "admin_handler"
    assert getattr(admin_handler, "__wrapped__", None) is not None


def test_sensitive_routes_enforce_explicit_api_key_policy(
    tmp_path: Path,
) -> None:
    """Ensure every /api/admin/*, /api/extended/keys*, and /api/user/* route has an explicit API key policy."""
    config = ServerConfig(storage_dir=str(tmp_path / "storage"))
    app = create_app(config)

    # Read-only self-profile query endpoints intentionally accessible to SDK/CLI API keys
    allowed_api_key_user_routes = {
        "/api/user/query",
        "/api/user/query/info",
    }

    inspected = 0
    for route in app.router.routes():
        resource = route.resource
        if resource is None:
            continue
        canonical = resource.canonical
        handler = route.handler

        if canonical.startswith("/api/admin/") or canonical.startswith(
            "/api/extended/keys"
        ):
            inspected += 1
            assert getattr(handler, "interactive_session_only", False) is True, (
                f"Route {route.method} {canonical} must deny static API keys via @interactive_session_only"
            )
        elif canonical.startswith("/api/user/"):
            inspected += 1
            is_public = getattr(handler, "is_public", False)
            is_interactive = getattr(handler, "interactive_session_only", False)
            assert (
                is_public or is_interactive or canonical in allowed_api_key_user_routes
            ), (
                f"Route {route.method} {canonical} must be explicitly classified "
                f"(@public_route, @interactive_session_only, or allowlisted)"
            )

    assert inspected >= 15
