"""HTTP transport platform component (`HttpComponent` and `HttpRegistrar`).

Owns reverse-proxy header setup (`aiohttp_remotes`), `jwt_auth_middleware`,
middleware ordering, public-prefix / ASGI resource auth exemptions, and deferred
catch-all resource mounting for components declaring ``platforms = ("http",)``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

import aiohttp_remotes
from aiohttp import web
from aiohttp.typedefs import Middleware
from aiohttp.web_urldispatcher import SystemRoute

from supernote.models.base import create_error_response
from supernote.server.core import ServerCore
from supernote.server.events import bind_event_actor
from supernote.server.keys import (
    HTTP_REGISTRAR_KEY,
    REQUEST_ACTOR_KEY,
    REQUEST_EQUIPMENT_NO_KEY,
    REQUEST_USER_KEY,
    USER_SERVICE_KEY,
)
from supernote.server.trace import trace_middleware
from supernote.server.utils.auth_utils import get_token_from_request

__all__ = [
    "HTTP_REGISTRAR_KEY",
    "HttpComponent",
    "HttpRegistrar",
    "jwt_auth_middleware",
]


@web.middleware
async def jwt_auth_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Authenticate requests via JWT, OAuth Bearer token, or static API key."""
    route = request.match_info.route
    if route is None or isinstance(route, SystemRoute):
        return await handler(request)

    http_registrar = request.app.get(HTTP_REGISTRAR_KEY)
    if (
        http_registrar is not None
        and route.resource is not None
        and route.resource in http_registrar.public_resources
    ):
        return await handler(request)

    handler_func = getattr(route, "handler", None)
    if handler_func and getattr(handler_func, "is_public", False):
        return await handler(request)

    if http_registrar is not None and any(
        request.path.startswith(p) for p in http_registrar.public_prefixes
    ):
        return await handler(request)

    if not (token := get_token_from_request(request)):
        return web.json_response(
            create_error_response("Unauthorized").to_dict(), status=401
        )

    user_service = request.app[USER_SERVICE_KEY]
    session = await user_service.verify_token(token)
    if not session:
        return web.json_response(
            create_error_response("Invalid token").to_dict(), status=401
        )

    if not session.is_interactive_session and getattr(
        handler_func, "interactive_session_only", False
    ):
        return web.json_response(
            create_error_response("Forbidden: Interactive session required").to_dict(),
            status=403,
        )

    request[REQUEST_USER_KEY] = session.email
    request[REQUEST_EQUIPMENT_NO_KEY] = session.equipment_no
    request[REQUEST_ACTOR_KEY] = session.actor
    with bind_event_actor(session.actor):
        return await handler(request)


class HttpRegistrar:
    """Registrar passed into ``<component>.http:async_setup_http(core, registrar)``."""

    def __init__(self) -> None:
        self._outer_middlewares: list[Middleware] = []
        self._inner_middlewares: list[Middleware] = []
        self._public_prefixes: list[str] = []
        self._public_resources: list[web.AbstractResource] = []
        self._known_resource_paths: set[str] = set()

    def add_middleware(
        self,
        middleware: Middleware,
        *,
        pre_auth: bool = False,
    ) -> None:
        """Register an aiohttp middleware to run outside (`pre_auth=True`) or inside auth."""
        if pre_auth:
            self._outer_middlewares.append(middleware)
        else:
            self._inner_middlewares.append(middleware)

    def add_public_prefix(self, prefix: str) -> None:
        """Register a URL path prefix exempted from `jwt_auth_middleware`."""
        if not prefix.startswith("/"):
            raise ValueError(f"Public path prefix must start with '/': {prefix!r}")
        if prefix not in self._public_prefixes:
            self._public_prefixes.append(prefix)

    def add_public_resource(
        self,
        resource: web.AbstractResource,
        *,
        known_paths: Iterable[str] = (),
    ) -> None:
        """Register an aiohttp resource (e.g. catch-all ASGI mount) exempted from auth."""
        if resource not in self._public_resources:
            self._public_resources.append(resource)
        self._known_resource_paths.update(known_paths)

    def mount_resources(self, app: web.Application) -> None:
        """Idempotently mount deferred public resources onto ``app.router`` after regular routes."""
        existing = set(app.router.resources())
        for resource in self._public_resources:
            if resource not in existing:
                app.router.register_resource(resource)
                existing.add(resource)

    def apply_to_app(self, app: web.Application) -> None:
        """Mount deferred resources and assemble the ordered middleware pipeline."""
        self.mount_resources(app)
        app.middlewares.extend(self._outer_middlewares)
        app.middlewares.append(trace_middleware)
        app.middlewares.append(jwt_auth_middleware)
        app.middlewares.extend(self._inner_middlewares)

    @property
    def outer_middlewares(self) -> tuple[Middleware, ...]:
        """Middlewares registered to run before trace and auth middlewares."""
        return tuple(self._outer_middlewares)

    @property
    def inner_middlewares(self) -> tuple[Middleware, ...]:
        """Middlewares registered to run after auth middleware."""
        return tuple(self._inner_middlewares)

    @property
    def public_prefixes(self) -> tuple[str, ...]:
        """Registered URL path prefixes exempted from `jwt_auth_middleware`."""
        return tuple(self._public_prefixes)

    @property
    def public_resources(self) -> tuple[web.AbstractResource, ...]:
        """Registered aiohttp resources exempted from `jwt_auth_middleware`."""
        return tuple(self._public_resources)

    @property
    def known_resource_paths(self) -> frozenset[str]:
        """Bounded canonical paths exposed by registered resources for metrics labeling."""
        return frozenset(self._known_resource_paths)


class HttpComponent:
    """Platform host component for HTTP proxy handling, middlewares, and auth exemptions."""

    domain = "http"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    hosted_platforms: tuple[str, ...] = ("http",)

    def __init__(self) -> None:
        self._registrar: HttpRegistrar | None = None

    def get_platform_registrar(self) -> HttpRegistrar:
        """Return the `HttpRegistrar` initialized during `async_setup`."""
        assert self._registrar is not None
        return self._registrar

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Configure reverse-proxy handling and initialize `HttpRegistrar` on ``core.app``."""
        if core.config.proxy_mode == "strict":
            trusted = [[ip] for ip in core.config.trusted_proxies]
            await aiohttp_remotes.setup(
                core.app,
                aiohttp_remotes.XForwardedStrict(trusted),
            )
        elif core.config.proxy_mode == "relaxed":
            await aiohttp_remotes.setup(core.app, aiohttp_remotes.XForwardedRelaxed())

        registrar = HttpRegistrar()
        self._registrar = registrar
        core.app[HTTP_REGISTRAR_KEY] = registrar

    async def async_finalize_platforms(self, core: ServerCore) -> None:
        """Mount deferred public resources and assemble the ordered middleware pipeline."""
        self.get_platform_registrar().apply_to_app(core.app)

    async def async_start(self, core: ServerCore) -> None:
        """No-op; `aiohttp` starts serving after `on_startup` completes."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; `aiohttp` handles HTTP server teardown."""
