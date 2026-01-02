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

from supernote.client.client import Client
from supernote.client.file import FileClient
from supernote.server.app import create_app
from supernote.server.config import AuthConfig, ServerConfig, UserEntry
from supernote.server.db.base import Base
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.coordination import LocalCoordinationService
from supernote.server.services.state import StateService
from supernote.server.services.storage import StorageService
from supernote.server.services.user import JWT_ALGORITHM, UserService
from supernote.server.services.vfs import VirtualFileSystem

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
    test_user = UserEntry(
        username=TEST_USERNAME,
        password_md5=hashlib.md5(TEST_PASSWORD.encode("utf-8")).hexdigest(),
        is_active=True,
        display_name="Test User",
    )

    return ServerConfig(
        trace_log_file=mock_trace_log,
        storage_dir=str(storage_root),
        auth=AuthConfig(
            users=[test_user],
            secret_key="test-secret-key",
        ),
    )


@pytest.fixture(autouse=True)
def patch_server_config(server_config: ServerConfig) -> Generator[None, None, None]:
    """Automatically patch server config for all server tests."""
    with patch("supernote.server.config.ServerConfig.load", return_value=server_config):
        yield


@pytest.fixture
def coordination_service() -> LocalCoordinationService:
    """Shared coordination service for tests."""
    return LocalCoordinationService()


@pytest.fixture(autouse=True)
def patch_coordination_service(
    coordination_service: LocalCoordinationService,
) -> Generator[None, None, None]:
    """Ensure the app uses our test coordination service instance."""
    with patch(
        "supernote.server.app.LocalCoordinationService",
        return_value=coordination_service,
    ):
        yield


@pytest.fixture(name="auth_headers")
async def auth_headers_fixture(
    server_config: ServerConfig,
    state_service: StateService,
    coordination_service: LocalCoordinationService,
) -> dict[str, str]:
    """Generate auth headers and persist session in state."""
    secret = server_config.auth.secret_key
    token = jwt.encode({"sub": TEST_USERNAME}, secret, algorithm=JWT_ALGORITHM)

    # Write to StateService (Legacy)
    state_service.create_session(token, TEST_USERNAME)

    # Write to CoordinationService (New)
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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

    def __init__(
        self,
        storage_service: StorageService,
        user_service: UserService,
        session_manager: DatabaseSessionManager,
    ) -> None:
        """Initialize the helper with a StorageService instance and an optional session manager."""
        self.storage_service = storage_service
        self.user_service = user_service
        self.session_manager = session_manager

    async def create_file(
        self, user: str, rel_path: str, content: str = "content"
    ) -> Path:
        """Create a file for a user in the storage service and BlobStorage."""
        # 1. Write to physical path (legacy/hybrid support)
        path = self.storage_service.resolve_path(user, rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

        user_id = await self.user_service.get_user_id(user)

        # 2. Write to BlobStorage
        content_bytes = content.encode()
        content_md5 = hashlib.md5(content_bytes).hexdigest()
        await self.storage_service.write_blob(content_bytes)

        # 3. Create VFS Entry
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            filename = path.name
            parent_path = str(Path(rel_path).parent)
            if parent_path == ".":
                parent_path = ""

            parent_id = await vfs.ensure_directory_path(user_id, parent_path)

            # Check if file exists and delete/overwrite or skip
            existing = await vfs.resolve_path(user_id, rel_path)
            if existing:
                await vfs.delete_node(user_id, existing.id)

            await vfs.create_file(
                user_id, parent_id, filename, len(content_bytes), content_md5
            )

        return path

    async def create_directory(self, user: str, rel_path: str) -> Path:
        """Create a directory for a user in the storage service."""
        path = self.storage_service.resolve_path(user, rel_path)
        path.mkdir(parents=True, exist_ok=True)

        user_id = int(hashlib.md5(user.encode()).hexdigest()[:15], 16)

        async with self.session_manager.session() as session:
            stmt = select(UserDO).where(UserDO.username == user)
            res = await session.execute(stmt)
            if not res.scalar_one_or_none():
                session.add(UserDO(id=user_id, username=user))
                await session.flush()

            vfs = VirtualFileSystem(session)
            await vfs.ensure_directory_path(user_id, rel_path)

        return path


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    """Provides a StorageService instance for testing."""
    return tmp_path / "storage"


@pytest.fixture
def storage_service(storage_root: Path) -> StorageService:
    """Provides a StorageService instance for testing."""
    return StorageService(storage_root)


@pytest.fixture
def state_service(storage_service: StorageService) -> StateService:
    """Provides a StateService instance for testing."""
    return StateService(storage_service.system_dir / "state.json")


@pytest.fixture
def user_service(
    server_config: ServerConfig,
    state_service: StateService,
    coordination_service: LocalCoordinationService,
    session_manager: DatabaseSessionManager,
) -> UserService:
    """Provides a UserService instance for testing."""
    return UserService(
        server_config.auth, state_service, coordination_service, session_manager
    )


@pytest.fixture
def user_storage(
    storage_service: StorageService,
    user_service: UserService,
    session_manager: DatabaseSessionManager,
) -> UserStorageHelper:
    """Fixture to easily create test files/folders for users."""
    return UserStorageHelper(storage_service, user_service, session_manager)


@pytest.fixture
async def mock_storage(
    storage_root: Path,
    storage_service: StorageService,
    session_manager: DatabaseSessionManager,
    user_storage: UserStorageHelper,
) -> AsyncGenerator[Path, None]:
    """Mock storage setup for all tests."""
    # Create default folders for the test user
    await user_storage.create_directory(TEST_USERNAME, "Note")
    await user_storage.create_directory(TEST_USERNAME, "Document")
    await user_storage.create_directory(TEST_USERNAME, "EXPORT")

    yield storage_root


@pytest.fixture(name="client")
async def client_fixture(
    aiohttp_client: AiohttpClient,
    server_config: ServerConfig,
    mock_storage: Path,
    session_manager: DatabaseSessionManager,
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
    from supernote.client.auth import AbstractAuth
    from supernote.client.client import Client

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
