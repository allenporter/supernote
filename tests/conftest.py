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
    # Ensure roots exist
    storage_root.mkdir(parents=True, exist_ok=True)
    (tmp_path / "temp").mkdir(parents=True, exist_ok=True)

    # Create default folders for the test user
    from tests.conftest import TEST_USERNAME

    user_root = storage_root / TEST_USERNAME
    user_root.mkdir(parents=True, exist_ok=True)
    (user_root / "Note").mkdir(exist_ok=True)
    (user_root / "Document").mkdir(exist_ok=True)
    (user_root / "EXPORT").mkdir(exist_ok=True)

    yield storage_root
