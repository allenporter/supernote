"""Root conftest for all tests."""

from pathlib import Path
from typing import Awaitable, Callable, Generator

import pytest
from aiohttp.test_utils import TestClient
from aiohttp.web import Application

# Register server test fixtures as a plugin
# pytest_plugins = ["tests.server.fixtures"]

# Shared test constants
TEST_USERNAME = "test@example.com"
TEST_PASSWORD = "testpassword"

# Type alias for the aiohttp_client fixture - shared across all tests
AiohttpClient = Callable[[Application], Awaitable[TestClient]]


@pytest.fixture(autouse=True)
def mock_storage(tmp_path: Path) -> Generator[Path, None, None]:
    """Mock storage directory for all tests."""
    storage_root = tmp_path / "storage"
    temp_root = tmp_path / "storage" / "temp"
    storage_root.mkdir(parents=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    # Create default folders
    (storage_root / "Note").mkdir()
    (storage_root / "Document").mkdir()
    (storage_root / "EXPORT").mkdir()

    yield storage_root
