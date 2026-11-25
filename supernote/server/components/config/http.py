"""HTTP platform setup for the `config` component.

Exposes administrator-only endpoints (guarded by `@require_admin`):
- `GET /api/extended/system/components`: list built-in components, their
  effective configuration provenance (`env`, `yaml`, `database`, `default`),
  running state, effective config, and schema fields.
- `PUT /api/extended/system/components/{domain}`: validate, persist, and (for
  `runtime_configurable` components) live-apply component configuration updates.
"""

from __future__ import annotations

import json

from aiohttp import web
from mashumaro.exceptions import InvalidFieldValue, MissingField

from supernote.server.components.http import HttpRegistrar
from supernote.server.core import ServerCore
from supernote.server.exceptions import (
    InvalidInputError,
    SupernoteError,
)
from supernote.server.routes.decorators import require_admin

from .models import (
    ComponentListResponseVO,
    ComponentStatusResponseVO,
    UpdateComponentConfigDTO,
)
from .service import CONFIG_SERVICE_KEY

__all__ = [
    "async_setup_http",
    "handle_list_system_components",
    "handle_update_system_component",
]


@require_admin
async def handle_list_system_components(request: web.Request) -> web.Response:
    """Return runtime status and configuration provenance for all built-in components."""
    try:
        config_service = request.app[CONFIG_SERVICE_KEY]
        statuses = await config_service.list_component_statuses()
        return web.json_response(ComponentListResponseVO(components=statuses).to_dict())
    except SupernoteError as err:
        return err.to_response()


@require_admin
async def handle_update_system_component(request: web.Request) -> web.Response:
    """Update and persist dynamic configuration for a built-in component."""
    try:
        domain = request.match_info.get("domain", "").strip()
        try:
            dto = UpdateComponentConfigDTO.from_json(await request.text())
        except (
            json.JSONDecodeError,
            InvalidFieldValue,
            MissingField,
            TypeError,
            ValueError,
        ) as err:
            raise InvalidInputError(f"Invalid request payload: {err}") from err

        config_service = request.app[CONFIG_SERVICE_KEY]
        status = await config_service.update_component_config(domain, dto.config)
        return web.json_response(ComponentStatusResponseVO(component=status).to_dict())
    except SupernoteError as err:
        return err.to_response()


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register component configuration management routes on ``registrar.router``."""
    del core
    registrar.router.add_get(
        "/api/extended/system/components",
        handle_list_system_components,
    )
    registrar.router.add_put(
        "/api/extended/system/components/{domain}",
        handle_update_system_component,
    )
