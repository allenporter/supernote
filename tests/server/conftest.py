"""Shared pytest fixtures for server tests.

This module is automatically discovered by pytest as a plugin.
"""

import hashlib
import logging
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from unittest.mock import patch

import jwt
import pytest
from aiohttp.test_utils import TestClient
from pytest_aiohttp import AiohttpClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import StaticPool

from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.file import FileClient
from supernote.server.app import create_app
from supernote.server.config import AuthConfig, ServerConfig
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage, LocalBlobStorage
from supernote.server.services.coordination import (
    CoordinationService,
    SqliteCoordinationService,
)
from supernote.server.services.user import JWT_ALGORITHM, UserService

TEST_USERNAME = "test@example.com"
TEST_PASSWORD = "testpassword"


# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(autouse=True)
def ignore_aiossqllite_debug() -> None:
    """Always ignore debug logs from aiosqlite since they are too verbose."""
    logging.getLogger("aiosqlite").setLevel(logging.INFO)


@pytest.fixture
def mock_trace_log(tmp_path: Path) -> Generator[str, None, None]:
    """Create a temporary trace log file for testing."""
    log_file = tmp_path / "trace.log"
    yield str(log_file)


@pytest.fixture
def server_config(mock_trace_log: str, storage_root: Path) -> ServerConfig:
    """Create a ServerConfig object for testing."""
    return ServerConfig(
        trace_log_file=mock_trace_log,
        storage_dir=str(storage_root),
        auth=AuthConfig(
            enable_registration=True,
            expiration_hours=1,
            secret_key="test-secret-key",
        ),
    )


@pytest.fixture(autouse=True)
def patch_server_config(server_config: ServerConfig) -> Generator[None, None, None]:
    """Automatically patch server config for all server tests."""
    with patch("supernote.server.config.ServerConfig.load", return_value=server_config):
        yield


@pytest.fixture(autouse=True)
def coordination_service(
    session_manager: DatabaseSessionManager,
) -> Generator[CoordinationService, None, None]:
    """Shared coordination service for tests."""
    coordination_service = SqliteCoordinationService(session_manager)
    with patch(
        "supernote.server.app.create_coordination_service",
        return_value=coordination_service,
    ):
        yield coordination_service


@pytest.fixture
async def test_users() -> list[str]:
    """Fixture with test users to create."""
    return [TEST_USERNAME, "a"]


@pytest.fixture
async def create_test_user(
    session_manager: DatabaseSessionManager, test_users: list[str]
) -> None:
    """Create the default test user in the database."""

    async with session_manager.session() as session:
        for test_user in test_users:
            stmt = select(UserDO).where(UserDO.email == test_user)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if not user:
                user = UserDO(
                    email=test_user,
                    password_md5=hashlib.md5(TEST_PASSWORD.encode("utf-8")).hexdigest(),
                    is_active=True,
                    display_name="Test User",
                )
                session.add(user)
                await session.commit()


@pytest.fixture(name="auth_headers")
async def auth_headers_fixture(
    server_config: ServerConfig,
    coordination_service: SqliteCoordinationService,
    create_test_user: None,
) -> dict[str, str]:
    """Generate auth headers and persist session in state."""
    secret = server_config.auth.secret_key

    token = jwt.encode({"sub": TEST_USERNAME}, secret, algorithm=JWT_ALGORITHM)

    # Write to CoordinationService
    session_val = f"{TEST_USERNAME}|"
    await coordination_service.set_value(f"session:{token}", session_val, ttl=3600)

    return {"x-access-token": token}


@pytest.fixture(name="session_manager")
async def session_manager_fixture() -> AsyncGenerator[DatabaseSessionManager, None]:
    """Create a session manager for tests."""
    session_manager = DatabaseSessionManager(
        TEST_DATABASE_URL,
        engine_kwargs={
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        },
    )
    engine = session_manager._engine
    assert engine is not None
    await session_manager.create_all_tables()

    with patch(
        "supernote.server.app.create_db_session_manager", return_value=session_manager
    ):
        yield session_manager


@pytest.fixture(scope="function")
async def db_session(
    session_manager: DatabaseSessionManager,
) -> AsyncGenerator[AsyncSession, None]:
    """Get a database session."""
    async with session_manager.session() as session:
        yield session


class UserStorageHelper:
    """Helper to create test files/folders for users."""

    def __init__(self, file_client: FileClient, storage_root: Path) -> None:
        """Initialize the helper."""
        self.file_client = file_client
        self.storage_root = storage_root

    async def create_file(
        self, user: str, rel_path: str, content: str = "content"
    ) -> None:
        """Create a file for a user using the FileClient API."""
        await self.file_client.upload_content(
            path=rel_path, content=content, equipment_no="TEST_DEVICE"
        )

    async def create_directory(self, user: str, rel_path: str) -> None:
        """Create a directory for a user using VFS."""
        await self.file_client.create_folder(rel_path, "TEST_DEVICE")


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    """Provides a StorageService instance for testing."""
    return tmp_path / "storage"


@pytest.fixture
def blob_storage(storage_root: Path) -> BlobStorage:
    """Provides a BlobStorage instance for testing."""
    return LocalBlobStorage(storage_root)


@pytest.fixture
def user_service(
    server_config: ServerConfig,
    coordination_service: SqliteCoordinationService,
    session_manager: DatabaseSessionManager,
) -> UserService:
    """Provides a UserService instance for testing."""
    return UserService(server_config.auth, coordination_service, session_manager)


@pytest.fixture
def user_storage(
    file_client: FileClient,
    storage_root: Path,
) -> UserStorageHelper:
    """Fixture to easily create test files/folders for users."""
    return UserStorageHelper(file_client, storage_root)


@pytest.fixture(autouse=True)
async def mock_storage(
    storage_root: Path,
    user_storage: UserStorageHelper,
    test_users: list[str],
) -> AsyncGenerator[Path, None]:
    """Mock storage setup for all tests."""
    for test_user in test_users:
        await user_storage.create_directory(test_user, "Note")
        await user_storage.create_directory(test_user, "Document")
        await user_storage.create_directory(test_user, "EXPORT")

    yield storage_root


@pytest.fixture(name="client")
async def client_fixture(
    aiohttp_client: AiohttpClient,
    server_config: ServerConfig,
    # mock_storage: Path, # REMOVED to break cycle
    session_manager: DatabaseSessionManager,
    coordination_service: SqliteCoordinationService,
) -> TestClient:
    """Create a test client for server tests."""
    app = create_app(server_config)
    return await aiohttp_client(app)


@pytest.fixture
async def authenticated_client(
    client: TestClient,
    auth_headers: dict[str, str],
) -> AsyncGenerator[Client, None]:
    """Create an authenticated supernote client."""

    token = auth_headers["x-access-token"]

    class TokenAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            return token

    # client is TestClient, client.session is ClientSession
    base_url = str(client.make_url(""))
    supernote_client = Client(client.session, auth=TokenAuth(), host=base_url)
    yield supernote_client


@pytest.fixture
def file_client(authenticated_client: Client) -> Generator[FileClient, None, None]:
    """Create a FileClient."""
    from supernote.client.file import FileClient

    yield FileClient(authenticated_client)
