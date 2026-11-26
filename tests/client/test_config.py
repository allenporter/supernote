"""Unit tests for `supernote.client.config.ConfigClient`."""

from unittest.mock import AsyncMock

from supernote.client.client import Client
from supernote.client.config import ConfigClient
from supernote.models.config import (
    ComponentConfigSource,
    ComponentListResponseVO,
    ComponentStatusResponseVO,
    ComponentStatusVO,
    ServerFeaturesVO,
)


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


async def test_config_client_list_components_unwraps_envelope() -> None:
    """Verify list_components returns the `components` list from the response envelope."""
    mock_client = AsyncMock(spec=Client)
    status = ComponentStatusVO(
        domain="wiki",
        enabled=False,
        running=False,
        source=ComponentConfigSource.DEFAULT,
        read_only=False,
        runtime_configurable=False,
    )
    mock_client.get_json.return_value = ComponentListResponseVO(components=[status])

    assert await ConfigClient(mock_client).list_components() == [status]
    mock_client.get_json.assert_awaited_once_with(
        "/api/extended/system/components", ComponentListResponseVO
    )


async def test_config_client_update_component_sends_config() -> None:
    """Verify update_component PUTs `{"config": ...}` and returns the updated status."""
    mock_client = AsyncMock(spec=Client)
    status = ComponentStatusVO(
        domain="webhooks",
        enabled=True,
        running=True,
        source=ComponentConfigSource.DATABASE,
        read_only=False,
        runtime_configurable=True,
    )
    mock_client.put_json.return_value = ComponentStatusResponseVO(component=status)

    result = await ConfigClient(mock_client).update_component(
        "webhooks", {"enabled": True}
    )

    assert result == status
    mock_client.put_json.assert_awaited_once_with(
        "/api/extended/system/components/webhooks",
        ComponentStatusResponseVO,
        json={"config": {"enabled": True}},
    )
