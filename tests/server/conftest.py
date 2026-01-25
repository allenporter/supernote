"""Shared pytest fixtures for server tests.

This module is automatically discovered by pytest as a plugin.
"""

import hashlib
import logging
import socket
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from aiohttp.test_utils import TestClient
from pytest_aiohttp import AiohttpClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import supernote.server.db.models  # noqa: F401
from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.device import DeviceClient
from supernote.client.web import WebClient
from supernote.models.user import UserRegisterDTO
from supernote.server.app import create_app
from supernote.server.config import AuthConfig, ServerConfig
from supernote.server.db.base import Base
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
def mock_trace_log(tmp_path: Path) -> str | None:
    """Create a temporary trace log file for testing.

    Defaults to None (disabled) for performance.
    Can be overridden by individual tests or modules.
    """
    return None


@pytest.fixture
def proxy_mode() -> str | None:
    """Default proxy mode for tests. Can be overridden by individual tests.

    Defaults to None (disabled) to match production default behavior.
    Tests that need proxy header handling should override this fixture.
    """
    return None


def pick_port() -> int:
    """Find a free port on the host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def server_port() -> int:
    """Find a free port for the main server."""
    return pick_port()


@pytest.fixture
def mcp_port() -> int:
    """Find a free port for the MCP server."""
    return pick_port()


@pytest.fixture
def server_config(
    mock_trace_log: str,
    storage_root: Path,
    proxy_mode: str | None,
    server_port: int,
    mcp_port: int,
) -> ServerConfig:
    """Create a ServerConfig object for testing."""
    return ServerConfig(
        trace_log_file=mock_trace_log,
        storage_dir=str(storage_root),
        port=server_port,
        mcp_port=mcp_port,
        proxy_mode=proxy_mode,
        _base_url=f"http://127.0.0.1:{server_port}",
        _mcp_base_url=f"http://127.0.0.1:{mcp_port}",
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


@pytest.fixture
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
        # Ensure clean state
        if await user_service.check_user_exists(test_user):
            await user_service.unregister(test_user)

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

    return {
        "x-access-token": token,
        "Authorization": f"Bearer {token}",
    }


@pytest.fixture(scope="session")
async def _session_manager_shared(
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncGenerator[DatabaseSessionManager, None]:
    """Create a singleton session manager for the entire test session."""
    tmp_dir = tmp_path_factory.mktemp("db")
    db_path = tmp_dir / "test_db.sqlite"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    session_manager = DatabaseSessionManager(
        db_url,
        engine_kwargs={
            "connect_args": {"check_same_thread": False},
        },
    )
    await session_manager.create_all_tables()
    # Prevent anyone (like app startup or cleanup) from redundant work/closing
    session_manager.create_all_tables = AsyncMock()  # type: ignore
    real_close = session_manager.close
    session_manager.close = AsyncMock()  # type: ignore
    yield session_manager
    # Actually close it at the end of the session
    await real_close()


@pytest.fixture(name="session_manager")
async def session_manager_fixture(
    _session_manager_shared: DatabaseSessionManager,
) -> AsyncGenerator[DatabaseSessionManager, None]:
    """Provide a session manager and clean up data after each test."""

    with patch(
        "supernote.server.app.create_db_session_manager",
        return_value=_session_manager_shared,
    ):
        yield _session_manager_shared

    # Truncate all tables to ensure isolation between tests efficiently
    # In the future if we have AUTOINCREMENT counters:
    #   DELETE FROM sqlite_sequence
    async with _session_manager_shared.session() as session:
        for table in reversed(Base.metadata.sorted_tables):
            # Wrap in try/except to handle cases where a table in metadata
            # wasn't created (e.g. import race conditions) or was dropped.
            try:
                await session.execute(text(f"DELETE FROM {table.name}"))
            except Exception:
                # Warning: Failed to truncate table. This is usually fine if the table doesn't exist.
                pass
        await session.commit()


@pytest.fixture
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
