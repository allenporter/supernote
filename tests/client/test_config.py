"""Unit tests for `supernote.client.config.ConfigClient`."""

from unittest.mock import AsyncMock

from supernote.client.client import Client
from supernote.client.config import ConfigClient
from supernote.models.config import ServerFeaturesVO


async def test_config_client_get_features() -> None:
    """Verify ConfigClient fetches and parses the running component list."""
    mock_client = AsyncMock(spec=Client)
    expected_vo = ServerFeaturesVO(running_components=["schedule", "search"])
    mock_client.get_json.return_value = expected_vo

    result = await ConfigClient(mock_client).get_features()

    assert result == expected_vo
    mock_client.get_json.assert_awaited_once_with(
        "/api/extended/system/features", ServerFeaturesVO
    )
