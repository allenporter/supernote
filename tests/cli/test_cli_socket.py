"""Tests for supernote client socket CLI command."""

import argparse
from unittest.mock import AsyncMock, patch

import pytest

from supernote.cli.client import (
    add_parser,
    async_cloud_socket,
    subcommand_cloud_socket,
)
from supernote.models.socket import SocketMessageData


def test_add_parser_socket():
    """Verify that 'cloud socket' parser registers options correctly."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    parsed = parser.parse_args(
        ["cloud", "socket", "--duration", "5.0", "--type", "ANDROID"]
    )
    assert parsed.command == "cloud"
    assert parsed.cloud_command == "socket"
    assert parsed.duration == 5.0
    assert parsed.type == "ANDROID"
    assert parsed.func == subcommand_cloud_socket


@pytest.mark.asyncio
async def test_async_cloud_socket_success():
    """Test successful execution of async_cloud_socket CLI handler."""
    mock_auth = AsyncMock()
    mock_auth.async_get_access_token.return_value = "mock_jwt_token"

    mock_socket_client = AsyncMock()
    mock_socket_client.connect = AsyncMock()
    mock_socket_client.ping = AsyncMock()
    mock_socket_client.check_status = AsyncMock()
    mock_socket_client.disconnect = AsyncMock()

    sample_msg = SocketMessageData(code="0", msg="Success", msg_type="DIGEST-SYN")

    async def mock_messages():
        yield sample_msg

    mock_socket_client.messages = mock_messages

    with (
        patch(
            "supernote.cli.client.load_cached_auth",
            return_value=(mock_auth, "http://localhost:8080"),
        ),
        patch(
            "supernote.cli.client.SupernoteSocketClient",
            return_value=mock_socket_client,
        ),
    ):
        await async_cloud_socket(duration=0.1, conn_type="ANDROID", verbose=True)

        mock_socket_client.connect.assert_called_once()
        mock_socket_client.ping.assert_called_once()
        mock_socket_client.check_status.assert_called_once()
        mock_socket_client.disconnect.assert_called_once()


def test_subcommand_cloud_socket():
    """Test subcommand_cloud_socket entry point."""
    args = argparse.Namespace(duration=5.0, type="ANDROID", verbose=False)
    with (
        patch("supernote.cli.client.async_cloud_socket"),
        patch("asyncio.run") as mock_run,
    ):
        subcommand_cloud_socket(args)
        mock_run.assert_called_once()
