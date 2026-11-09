"""Tests for server and Web UI plugin host."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, make_mocked_request
from pytest_aiohttp import AiohttpClient

from supernote.server.config import ServerConfig
from supernote.server.events import LocalEventBus, NoteUpdatedEvent
from supernote.server.plugins import (
    PluginContext,
    ServerPluginDescriptor,
    create_plugins_routes,
    load_server_plugins,
)
from supernote.server.services.file import FileEntity, FileService
from supernote.server.services.user import UserService

TEST_USERNAME = "test@example.com"


async def test_plugin_context_get_authenticated_user_valid(
    client: TestClient,
) -> None:
    """Verify get_authenticated_user returns user when user is a non-empty string."""
    ctx: PluginContext = client.app["plugin_context"]
    request = make_mocked_request("GET", "/api/test", app=client.app)
    request["user"] = TEST_USERNAME

    assert ctx.get_authenticated_user(request) == TEST_USERNAME


async def test_plugin_context_get_authenticated_user_unauthorized(
    client: TestClient,
) -> None:
    """Verify get_authenticated_user raises HTTPUnauthorized when user is missing or empty."""
    ctx: PluginContext = client.app["plugin_context"]

    empty_request = make_mocked_request("GET", "/api/test", app=client.app)
    with pytest.raises(web.HTTPUnauthorized):
        ctx.get_authenticated_user(empty_request)

    blank_request = make_mocked_request("GET", "/api/test", app=client.app)
    blank_request["user"] = "   "
    with pytest.raises(web.HTTPUnauthorized):
        ctx.get_authenticated_user(blank_request)


async def test_plugin_context_get_user_plugin_dir(
    client: TestClient, tmp_path: Path
) -> None:
    """Verify get_user_plugin_dir sanitizes names and creates directories."""
    ctx: PluginContext = client.app["plugin_context"]
    plugin_dir = ctx.get_user_plugin_dir("user@domain.com", "plugin/test:1")

    assert plugin_dir.exists()
    assert plugin_dir.is_dir()
    assert "user_domain.com" in plugin_dir.name
    assert "plugin_test_1" in str(plugin_dir)


async def test_plugin_context_write_read_and_get_file_info(
    client: TestClient, create_test_user: None
) -> None:
    """Verify write_file_bytes, get_file_info, and read_file_bytes using real FileService."""
    ctx: PluginContext = client.app["plugin_context"]
    content = b"Plugin write test payload"

    entity = await ctx.write_file_bytes(TEST_USERNAME, "/Document/test.txt", content)
    assert isinstance(entity, FileEntity)
    assert entity.name == "test.txt"
    assert entity.size == len(content)
    assert not entity.is_folder

    info = await ctx.get_file_info(TEST_USERNAME, "/Document/test.txt")
    assert info is not None
    assert info.id == entity.id
    assert info.name == "test.txt"
    assert info.size == len(content)

    read_bytes = await ctx.read_file_bytes(TEST_USERNAME, "/Document/test.txt")
    assert read_bytes == content


async def test_plugin_context_read_file_bytes_not_found(
    client: TestClient, create_test_user: None
) -> None:
    """Verify read_file_bytes raises FileNotFoundError when target does not exist."""
    ctx: PluginContext = client.app["plugin_context"]
    with pytest.raises(FileNotFoundError):
        await ctx.read_file_bytes(TEST_USERNAME, "/Document/nonexistent.txt")


async def test_plugin_context_write_note_publishes_event(
    client: TestClient, create_test_user: None
) -> None:
    """Verify write_file_bytes publishes NoteUpdatedEvent for .note files."""
    ctx: PluginContext = client.app["plugin_context"]
    received_events: list[NoteUpdatedEvent] = []

    async def on_note_updated(event: NoteUpdatedEvent) -> None:
        received_events.append(event)

    ctx.event_bus.subscribe(NoteUpdatedEvent, on_note_updated)

    content = b"fake-note-data"
    entity = await ctx.write_file_bytes(TEST_USERNAME, "/Note/test_note.note", content)

    assert entity.name == "test_note.note"
    assert len(received_events) == 1
    assert received_events[0].file_id == entity.id
    assert received_events[0].file_path == entity.full_path


async def test_load_server_plugins_and_routes(
    aiohttp_client: AiohttpClient,
    server_config: ServerConfig,
    tmp_path: Path,
    auth_headers: dict[str, str],
) -> None:
    """Verify load_server_plugins registers routes, static assets, and api/extended/plugins."""
    static_dir = tmp_path / "plugin_ui"
    static_dir.mkdir(parents=True, exist_ok=True)
    ui_script = static_dir / "plugin.js"
    ui_script.write_text("console.log('plugin loaded');", encoding="utf-8")

    plugin_routes = web.RouteTableDef()

    @plugin_routes.get("/api/test-plugin/ping")
    async def ping_handler(request: web.Request) -> web.Response:
        return web.json_response({"pong": True})

    descriptor = ServerPluginDescriptor(
        plugin_id="demo_plugin",
        display_name="Demo Plugin",
        version="1.0.0",
        routes=plugin_routes,
        static_dir=static_dir,
        ui_module="plugin.js",
    )

    fake_ep = MagicMock()
    fake_ep.name = "demo_plugin"
    fake_ep.load.return_value = lambda ctx: descriptor

    app = web.Application()
    mock_file_service = MagicMock(spec=FileService)
    mock_user_service = MagicMock(spec=UserService)
    mock_event_bus = MagicMock(spec=LocalEventBus)
    ctx = PluginContext(
        file_service=mock_file_service,
        user_service=mock_user_service,
        event_bus=mock_event_bus,
        storage_dir=tmp_path,
    )

    with patch("importlib.metadata.entry_points", return_value=[fake_ep]):
        loaded = load_server_plugins(app, ctx)

    assert len(loaded) == 1
    assert loaded[0] == descriptor
    assert app["server_plugins"] == [descriptor]

    test_client = await aiohttp_client(app)

    # Calling plugin route
    ping_resp = await test_client.get("/api/test-plugin/ping")
    assert ping_resp.status == 200
    assert await ping_resp.json() == {"pong": True}

    # Calling plugin static asset
    static_resp = await test_client.get("/static/plugins/demo_plugin/plugin.js")
    assert static_resp.status == 200
    assert "console.log('plugin loaded');" in await static_resp.text()


async def test_get_server_plugins_endpoint_authenticated(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify GET /api/extended/plugins returns registered plugin metadata with auth."""
    resp = await client.get("/api/extended/plugins", headers=auth_headers)
    assert resp.status == 200
    data = await resp.json()
    assert "plugins" in data
    assert isinstance(data["plugins"], list)


async def test_get_server_plugins_endpoint_unauthorized(
    client: TestClient,
) -> None:
    """Verify GET /api/extended/plugins rejects requests without auth."""
    resp = await client.get("/api/extended/plugins")
    assert resp.status == 401


def test_create_plugins_routes_structure() -> None:
    """Verify create_plugins_routes creates route table with expected endpoint."""
    descriptor = ServerPluginDescriptor(
        plugin_id="desc_test",
        display_name="Desc Test",
        version="0.0.1",
        static_dir=Path("/tmp"),
        ui_module="module.js",
    )
    routes = list(create_plugins_routes([descriptor]))
    assert len(routes) == 1
    route = routes[0]
    assert isinstance(route, web.RouteDef)
    assert route.path == "/api/extended/plugins"
    assert route.method == "GET"
