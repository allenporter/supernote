"""Fixtures for MCP integration tests enabling the embedded MCP servers."""

import pytest


@pytest.fixture
def mcp_enabled() -> bool:
    """Enable MCP OAuth routes and Streamable HTTP server for MCP integration tests."""
    return True
