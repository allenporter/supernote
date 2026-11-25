"""Tests for ScheduleClient reactive token refresh and HTTP error handling."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from aiohttp import web
from pytest_aiohttp import AiohttpClient

from supernote.client import Client
from supernote.client.auth import AbstractAuth, ConstantAuth
from supernote.client.exceptions import (
    ApiException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from supernote.client.schedule import ScheduleClient


class RefreshableAuth(AbstractAuth):
    """Test auth provider with lock-deduplicated reactive token refresh."""

    def __init__(
        self,
        initial_token: str = "stale-token",
        refreshed_token: str | None = "fresh-token",
    ) -> None:
        self._token = initial_token
        self._refreshed_token = refreshed_token
        self._lock = asyncio.Lock()
        self.refresh_calls: list[str] = []

    async def async_get_access_token(self) -> str:
        return self._token

    async def async_refresh_access_token(self, failed_token: str) -> bool:
        self.refresh_calls.append(failed_token)
        if self._refreshed_token is None:
            return False
        async with self._lock:
            if self._token != failed_token:
                return True
            self._token = self._refreshed_token
            return True


async def handler_csrf(request: web.Request) -> web.Response:
    """Handle CSRF token request."""
    return web.Response(text="ok", headers={"X-XSRF-TOKEN": "test-csrf"})


@pytest.mark.parametrize(
    ("method", "path", "invoke", "expected_result"),
    [
        (
            "DELETE",
            "/api/file/schedule/group/group-1",
            lambda s: s.delete_group("group-1"),
            None,
        ),
        (
            "DELETE",
            "/api/file/schedule/task/task-1",
            lambda s: s.delete_task("task-1"),
            None,
        ),
        (
            "GET",
            "/api/schedule/feed.ics",
            lambda s: s.get_ical_feed(group_id="group-1"),
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n",
        ),
    ],
)
async def test_schedule_methods_refresh_and_retry_on_401(
    aiohttp_client: AiohttpClient,
    method: str,
    path: str,
    invoke: Callable[[ScheduleClient], Awaitable[str | None]],
    expected_result: str | None,
) -> None:
    """Verify delete_group, delete_task, and get_ical_feed refresh and retry on 401."""
    seen_tokens: list[str | None] = []
    seen_queries: list[str] = []

    async def handler(request: web.Request) -> web.Response:
        token = request.headers.get("x-access-token")
        seen_tokens.append(token)
        seen_queries.append(request.query.get("taskListId", ""))
        if token != "fresh-token":
            return web.Response(status=401, text="Expired")
        if expected_result is not None:
            return web.Response(text=expected_result, content_type="text/calendar")
        return web.json_response({"success": True})

    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_route(method, path, handler)
    srv = await aiohttp_client(app)

    auth = RefreshableAuth()
    client = Client(srv.session, host=str(srv.make_url("")), auth=auth)
    schedule = ScheduleClient(client)

    result = await invoke(schedule)
    assert result == expected_result
    assert seen_tokens == ["stale-token", "fresh-token"]
    assert auth.refresh_calls == ["stale-token"]
    if path == "/api/schedule/feed.ics":
        assert seen_queries == ["group-1", "group-1"]


async def test_get_ical_feed_without_group_id(aiohttp_client: AiohttpClient) -> None:
    """Verify get_ical_feed omits taskListId when group_id is None."""
    seen_params: list[dict[str, str]] = []
    ics_body = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"

    async def handler(request: web.Request) -> web.Response:
        seen_params.append(dict(request.query))
        return web.Response(text=ics_body, content_type="text/calendar")

    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_get("/api/schedule/feed.ics", handler)
    srv = await aiohttp_client(app)

    client = Client(srv.session, host=str(srv.make_url("")), auth=ConstantAuth("token"))
    schedule = ScheduleClient(client)

    assert await schedule.get_ical_feed() == ics_body
    assert seen_params == [{}]


@pytest.mark.parametrize(
    ("status", "exc_cls"),
    [
        (401, UnauthorizedException),
        (403, ForbiddenException),
        (404, NotFoundException),
        (500, ApiException),
    ],
)
@pytest.mark.parametrize(
    ("method", "path", "invoke"),
    [
        (
            "DELETE",
            "/api/file/schedule/group/group-1",
            lambda s: s.delete_group("group-1"),
        ),
        (
            "DELETE",
            "/api/file/schedule/task/task-1",
            lambda s: s.delete_task("task-1"),
        ),
        (
            "GET",
            "/api/schedule/feed.ics",
            lambda s: s.get_ical_feed(),
        ),
    ],
)
async def test_schedule_methods_raise_for_http_status(
    aiohttp_client: AiohttpClient,
    status: int,
    exc_cls: type[ApiException],
    method: str,
    path: str,
    invoke: Callable[[ScheduleClient], Awaitable[str | None]],
) -> None:
    """Verify delete_group, delete_task, and get_ical_feed map HTTP errors via _raise_for_status."""

    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=status, text=f"HTTP {status} error")

    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_route(method, path, handler)
    srv = await aiohttp_client(app)

    auth = RefreshableAuth(refreshed_token=None)
    client = Client(srv.session, host=str(srv.make_url("")), auth=auth)
    schedule = ScheduleClient(client)

    with pytest.raises(exc_cls):
        await invoke(schedule)

    if status == 401:
        assert auth.refresh_calls == ["stale-token"]
    else:
        assert auth.refresh_calls == []


@pytest.mark.parametrize(
    ("method", "path", "invoke"),
    [
        (
            "DELETE",
            "/api/file/schedule/group/group-1",
            lambda s: s.delete_group("group-1"),
        ),
        (
            "DELETE",
            "/api/file/schedule/task/task-1",
            lambda s: s.delete_task("task-1"),
        ),
        (
            "GET",
            "/api/schedule/feed.ics",
            lambda s: s.get_ical_feed(),
        ),
    ],
)
async def test_schedule_methods_retry_capped_at_one(
    aiohttp_client: AiohttpClient,
    method: str,
    path: str,
    invoke: Callable[[ScheduleClient], Awaitable[str | None]],
) -> None:
    """Verify 401 after refresh raises UnauthorizedException without retrying again."""
    attempts = 0

    async def handler(request: web.Request) -> web.Response:
        nonlocal attempts
        attempts += 1
        return web.Response(status=401, text="Still unauthorized")

    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_route(method, path, handler)
    srv = await aiohttp_client(app)

    auth = RefreshableAuth()
    client = Client(srv.session, host=str(srv.make_url("")), auth=auth)
    schedule = ScheduleClient(client)

    with pytest.raises(UnauthorizedException):
        await invoke(schedule)

    assert attempts == 2
    assert auth.refresh_calls == ["stale-token"]
