"""Client for the server component configuration API.

- `get_features()`: any signed-in user can list running component domains.
- `list_components()` / `update_component()`: administrator-only component
  status, configuration provenance, and configuration updates.
"""

from typing import Any
from urllib.parse import quote

from supernote.models.config import (
    ComponentListResponseVO,
    ComponentStatusResponseVO,
    ComponentStatusVO,
    ServerFeaturesVO,
    UpdateComponentConfigDTO,
)

from .client import Client
from .exceptions import ApiException

__all__ = ["ConfigClient"]


class ConfigClient:
    """Client for server component status and configuration."""

    def __init__(self, client: Client) -> None:
        """Initialize the ConfigClient."""
        self._client = client

    async def get_features(self) -> ServerFeaturesVO:
        """Fetch the domains of running built-in components (`GET /api/extended/system/features`)."""
        return await self._client.get_json(
            "/api/extended/system/features", ServerFeaturesVO
        )

    async def list_components(self) -> list[ComponentStatusVO]:
        """List status and configuration for all built-in components (`GET /api/extended/system/components`, admin only)."""
        resp = await self._client.get_json(
            "/api/extended/system/components", ComponentListResponseVO
        )
        return resp.components

    async def update_component(
        self, domain: str, config: dict[str, Any]
    ) -> ComponentStatusVO:
        """Persist configuration for one component (`PUT /api/extended/system/components/{domain}`, admin only)."""
        resp = await self._client.put_json(
            f"/api/extended/system/components/{quote(domain, safe='')}",
            ComponentStatusResponseVO,
            json=UpdateComponentConfigDTO(config=config).to_dict(),
        )
        if resp.component is None:
            raise ApiException(f"Server returned no status for component {domain!r}")
        return resp.component
