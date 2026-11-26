"""Client for the server component configuration API."""

from supernote.models.config import ServerFeaturesVO

from .client import Client

__all__ = ["ConfigClient", "ServerFeaturesVO"]


class ConfigClient:
    """Client for querying which server components are running."""

    def __init__(self, client: Client) -> None:
        """Initialize the ConfigClient."""
        self._client = client

    async def get_features(self) -> ServerFeaturesVO:
        """Fetch the domains of running built-in components (`GET /api/extended/system/features`)."""
        return await self._client.get_json(
            "/api/extended/system/features", ServerFeaturesVO
        )
