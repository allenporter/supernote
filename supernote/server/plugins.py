"""Declarative server and Web UI plugin host."""

import hashlib
import importlib.metadata
import inspect
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.events import LocalEventBus, NoteUpdatedEvent
from supernote.server.routes.decorators import authenticated_route
from supernote.server.services.file import FileEntity, FileService
from supernote.server.services.user import UserService

__all__ = [
    "PluginContext",
    "ServerPluginDescriptor",
    "create_plugins_routes",
    "load_server_plugins",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServerPluginDescriptor:
    plugin_id: str
    display_name: str
    version: str = "0.1.0"
    routes: web.RouteTableDef | Sequence[web.AbstractRouteDef] = ()
    static_dir: Path | None = None
    ui_module: str | None = None


class PluginContext:
    def __init__(
        self,
        file_service: FileService,
        user_service: UserService,
        event_bus: LocalEventBus,
        storage_dir: Path,
    ) -> None:
        self.file_service = file_service
        self.user_service = user_service
        self.event_bus = event_bus
        self.storage_dir = storage_dir

    def get_authenticated_user(self, request: web.Request) -> str:
        user = request.get("user")
        if not isinstance(user, str) or not user.strip():
            raise web.HTTPUnauthorized(reason="Authentication required")
        return user

    def get_user_plugin_dir(self, user: str, plugin_id: str) -> Path:
        safe_user = re.sub(r"[^a-zA-Z0-9_.-]", "_", user)
        safe_plugin = re.sub(r"[^a-zA-Z0-9_.-]", "_", plugin_id)
        plugin_dir = self.storage_dir / "plugins" / safe_plugin / safe_user
        plugin_dir.mkdir(parents=True, exist_ok=True)
        return plugin_dir

    async def get_file_info(self, user: str, storage_path: str) -> FileEntity | None:
        return await self.file_service.get_file_info(user, storage_path)

    async def read_file_bytes(self, user: str, storage_path: str) -> bytes:
        entity = await self.file_service.get_file_info(user, storage_path)
        if entity is None or entity.is_folder or not entity.storage_key:
            raise FileNotFoundError(f"File not found: {storage_path}")

        chunks: list[bytes] = []
        async for chunk in self.file_service.blob_storage.get(
            USER_DATA_BUCKET, entity.storage_key
        ):
            chunks.append(chunk)
        return b"".join(chunks)

    async def write_file_bytes(
        self, user: str, storage_path: str, data: bytes
    ) -> FileEntity:
        clean_path = storage_path.strip("/")
        if "/" in clean_path:
            parent_path, filename = clean_path.rsplit("/", 1)
        else:
            parent_path, filename = "", clean_path

        content_hash = hashlib.md5(data).hexdigest()
        await self.file_service.blob_storage.put(USER_DATA_BUCKET, content_hash, data)
        entity = await self.file_service.finish_upload(
            user=user,
            filename=filename,
            path_str=parent_path,
            content_hash=content_hash,
            inner_name=content_hash,
        )

        if filename.lower().endswith(".note"):
            user_id = await self.user_service.get_user_id(user)
            await self.event_bus.publish(
                NoteUpdatedEvent(
                    file_id=entity.id,
                    user_id=user_id,
                    file_path=entity.full_path,
                    defer_processing=False,
                )
            )

        return entity


def create_plugins_routes(
    descriptors: Sequence[ServerPluginDescriptor],
) -> web.RouteTableDef:
    routes = web.RouteTableDef()

    @routes.get("/api/extended/plugins")
    @authenticated_route
    async def get_server_plugins(request: web.Request) -> web.Response:
        plugins_data = [
            {
                "id": d.plugin_id,
                "name": d.display_name,
                "version": d.version,
                "uiModuleUrl": (
                    f"/static/plugins/{d.plugin_id}/{d.ui_module}"
                    if d.static_dir and d.ui_module
                    else None
                ),
            }
            for d in descriptors
        ]
        return web.json_response({"plugins": plugins_data})

    return routes


def _invoke_plugin_hook(hook: Any, ctx: PluginContext, app: web.Application) -> Any:
    try:
        sig = inspect.signature(hook)
        first_param = next(iter(sig.parameters.values()), None)
        if first_param is not None and (
            first_param.annotation is web.Application
            or (
                first_param.name == "app"
                and first_param.annotation is not PluginContext
            )
        ):
            return hook(app)
        return hook(ctx)
    except TypeError:
        return hook(app)


def load_server_plugins(
    app: web.Application, ctx: PluginContext
) -> list[ServerPluginDescriptor]:
    app["plugin_context"] = ctx
    descriptors: list[ServerPluginDescriptor] = []

    try:
        entry_points = importlib.metadata.entry_points(group="supernote.server_plugins")
    except Exception as e:
        logger.warning(f"Error querying server plugin entry points: {e}")
        entry_points = []

    for ep in entry_points:
        try:
            hook = ep.load()
            result = _invoke_plugin_hook(hook, ctx, app)

            if isinstance(result, ServerPluginDescriptor):
                if result.routes:
                    app.add_routes(result.routes)
                if result.static_dir and result.static_dir.is_dir():
                    app.router.add_static(
                        f"/static/plugins/{result.plugin_id}",
                        path=result.static_dir,
                        name=f"plugin_static_{result.plugin_id}",
                    )
                descriptors.append(result)
                logger.info(f"Loaded server plugin descriptor: {result.plugin_id}")
            elif isinstance(result, web.RouteTableDef):
                app.add_routes(result)
                descriptor = ServerPluginDescriptor(
                    plugin_id=ep.name,
                    display_name=ep.name,
                    routes=result,
                )
                descriptors.append(descriptor)
                logger.info(f"Loaded legacy route-table server plugin: {ep.name}")
            else:
                logger.info(f"Loaded server plugin: {ep.name}")
        except Exception as e:
            logger.exception(f"Failed to load server plugin {ep.name}: {e}")

    app.add_routes(create_plugins_routes(descriptors))
    app["server_plugins"] = descriptors
    return descriptors
