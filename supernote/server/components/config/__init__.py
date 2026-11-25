"""Dynamic component configuration vertical component (`config`).

Manages configuration for all built-in server components by combining static
settings from `SUPERNOTE_*` environment variables and `config.yaml` with dynamic
overrides stored in the database (`CoordinationService`). Environment variables
and explicit `config.yaml` sections always take precedence over database
settings, while unpinned components fall back to database overrides or their
built-in defaults.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from supernote.server.core import ServerCore
from supernote.server.keys import COMPONENT_LOADER_KEY

from .service import (
    CONFIG_SERVICE_KEY,
    ConfigService,
    async_resolve_component_configs,
    build_static_component_configs,
)

if TYPE_CHECKING:
    from supernote.server.config import ServerConfig

__all__ = [
    "ConfigComponent",
]


class ConfigComponent:
    """Built-in vertical component managing component configuration resolution and persistence."""

    domain: str = "config"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()

    def build_static_configs(self, config: ServerConfig) -> dict[str, dict[str, Any]]:
        """Build the static per-component configuration map from `ServerConfig`."""
        return build_static_component_configs(config)

    async def async_resolve_startup_configs(
        self, core: ServerCore
    ) -> dict[str, dict[str, Any]]:
        """Resolve effective per-component startup configuration across `env > yaml > database > default`."""
        resolved_entries = await async_resolve_component_configs(
            core.config, core.coordination
        )
        return {domain: entry.config for domain, entry in resolved_entries.items()}

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Initialize `ConfigService` and register it on `core.app`."""
        del config
        loader = core.app[COMPONENT_LOADER_KEY]
        core.app[CONFIG_SERVICE_KEY] = ConfigService(
            server_config=core.config,
            coordination=core.coordination,
            loader=loader,
        )

    async def async_start(self, core: ServerCore) -> None:
        """No background worker required for `ConfigComponent`."""
        del core

    async def async_stop(self, core: ServerCore) -> None:
        """No background resources to release on shutdown."""
        del core
