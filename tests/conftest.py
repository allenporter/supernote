"""Root conftest for all tests."""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Awaitable, Callable, Generator

import pytest
from aiohttp.test_utils import TestClient
from aiohttp.web import Application

from supernote.server.db.session import sessionmanager
from supernote.server.services.state import StateService
from supernote.server.services.storage import StorageService

pytest_plugins = [
    "tests.plugins.db_fixtures",
]


@pytest.fixture(scope="session", autouse=True)
async def shutdown_db_session() -> AsyncGenerator[None, None]:
    yield

    # Close the global sessionmanager if it was initialized
    try:
        await sessionmanager.close()
    except Exception:
        pass


# Shared test constants
TEST_USERNAME = "test@example.com"
TEST_PASSWORD = "testpassword"

# Type alias for the aiohttp_client fixture - shared across all tests
AiohttpClient = Callable[[Application], Awaitable[TestClient]]


class UserStorageHelper:
    def __init__(self, storage_service: StorageService):
        self.storage_service = storage_service

    def create_file(self, user: str, rel_path: str, content: str = "content") -> Path:
        path = self.storage_service.resolve_path(user, rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def create_directory(self, user: str, rel_path: str) -> Path:
        path = self.storage_service.resolve_path(user, rel_path)
        path.mkdir(parents=True, exist_ok=True)
        return path


@pytest.fixture
def storage_service(tmp_path: Path) -> StorageService:
    """Provides a StorageService instance for testing."""
    storage_root = tmp_path / "storage"
    return StorageService(storage_root)


@pytest.fixture
def state_service(storage_service: StorageService) -> StateService:
    """Provides a StateService instance for testing."""
    return StateService(storage_service.system_dir / "state.json")


@pytest.fixture
def user_storage(storage_service: StorageService) -> UserStorageHelper:
    """Fixture to easily create test files/folders for users."""
    return UserStorageHelper(storage_service)


@pytest.fixture(autouse=True)
def mock_storage(storage_service: StorageService) -> Generator[Path, None, None]:
    """Mock storage setup for all tests."""
    # Create default folders for the test user
    helper = UserStorageHelper(storage_service)
    helper.create_directory(TEST_USERNAME, "Note")
    helper.create_directory(TEST_USERNAME, "Document")
    helper.create_directory(TEST_USERNAME, "EXPORT")

    yield storage_service.root_dir
