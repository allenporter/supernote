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
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import StaticPool

from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.device import DeviceClient
from supernote.client.web import WebClient
from supernote.models.user import UserRegisterDTO
from supernote.server.app import create_app
from supernote.server.config import AuthConfig, ServerConfig
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
def proxy_mode() -> str | None:
    """Default proxy mode for tests. Can be overridden by individual tests.

    Defaults to None (disabled) to match production default behavior.
    Tests that need proxy header handling should override this fixture.
    """
    return None


@pytest.fixture
def server_config(
    mock_trace_log: str, storage_root: Path, proxy_mode: str | None
) -> ServerConfig:
    """Create a ServerConfig object for testing."""
    return ServerConfig(
        trace_log_file=mock_trace_log,
        storage_dir=str(storage_root),
        proxy_mode=proxy_mode,
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
    return [TEST_USERNAME, "a@example.com"]


@pytest.fixture
async def create_test_user(
    user_service: UserService,
    session_manager: DatabaseSessionManager,
    test_users: list[str],
) -> None:
    """Create the default test user in the database."""

    for test_user in test_users:
        result = await user_service.create_user(
            UserRegisterDTO(
                email=test_user,
                password=hashlib.md5(TEST_PASSWORD.encode("utf-8")).hexdigest(),
                user_name="Test User",
            )
        )
        assert result.id
        assert result.is_active


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


# @pytest.fixture(autouse=True)
# async def mock_storage(test_users: list[str], device_client: DeviceClient) -> None:
#     """Mock storage setup for the default device_client user."""
#     if test_users:
#         # await device_client.create_folder("Note", "TEST_DEVICE")
#         # await device_client.create_folder("Document", "TEST_DEVICE")
#         # await device_client.create_folder("EXPORT", "TEST_DEVICE")


@pytest.fixture(name="client")
async def client_fixture(
    aiohttp_client: AiohttpClient,
    server_config: ServerConfig,
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
def device_client(authenticated_client: Client) -> Generator[DeviceClient, None, None]:
    """Create a DeviceClient."""
    yield DeviceClient(authenticated_client)


@pytest.fixture
def web_client(authenticated_client: Client) -> Generator[WebClient, None, None]:
    """Create a WebClient."""
    yield WebClient(authenticated_client)
