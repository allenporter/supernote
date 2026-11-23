"""HTTP transport platform component (`HttpComponent` and `HttpRegistrar`).

Owns `aiohttp` middleware ordering, public-prefix / ASGI resource auth exemptions,
and deferred catch-all resource mounting for components declaring ``platforms = ("http",)``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from aiohttp import web
from aiohttp.typedefs import Middleware

from supernote.server.core import ServerCore
from supernote.server.keys import HTTP_REGISTRAR_KEY

__all__ = [
    "HTTP_REGISTRAR_KEY",
    "HttpComponent",
    "HttpRegistrar",
]


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
        """Mount deferred public resources onto ``app.router`` after regular routes."""
        for resource in self._public_resources:
            app.router.register_resource(resource)

    @property
    def outer_middlewares(self) -> tuple[Middleware, ...]:
        """Middlewares registered to run before trace and auth middlewares."""
        return tuple(self._outer_middlewares)

    @property
    def inner_middlewares(self) -> tuple[Middleware, ...]:
        """Middlewares registered to run after auth and cache-control middlewares."""
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
    """Platform host component for HTTP routes, middlewares, and auth exemptions."""

    domain = "http"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Initialize the shared `HttpRegistrar` on ``core.app``."""
        core.app[HTTP_REGISTRAR_KEY] = HttpRegistrar()

    async def async_start(self, core: ServerCore) -> None:
        """No-op; `aiohttp` starts serving after `on_startup` completes."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; `aiohttp` handles HTTP server teardown."""
