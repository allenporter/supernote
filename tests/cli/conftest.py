"""CLI-specific fixtures layered onto the root in-process server harness."""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.auth import FileCacheAuth
from supernote.models.user import UserRegisterDTO
from supernote.server.config import AiConfig, AuthConfig, ModelConfig, ServerConfig
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.user import UserService
from tests.fixtures.server import TEST_PASSWORD, TEST_USERNAME

ADMIN_EMAIL = TEST_USERNAME
ADMIN_PASSWORD = TEST_PASSWORD


@dataclass
class CliServerEnv:
    """Running test server environment for CLI tests."""

    url: str
    client: TestClient
    session_manager: DatabaseSessionManager
    user_service: UserService
    server_config: ServerConfig
    admin_token: str


@pytest.fixture(autouse=True)
def isolated_cli_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect HOME to tmp_path so ~/.cache/supernote.pkl is isolated per test."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def server_config(
    storage_root: Path,
    server_port: int,
    mcp_enabled: bool,
    mcp_port: int,
) -> ServerConfig:
    """Create a ServerConfig with fake AI models enabled for CLI tests."""
    return ServerConfig(
        host="127.0.0.1",
        storage_dir=str(storage_root),
        port=server_port,
        mcp_enabled=mcp_enabled,
        mcp_port=mcp_port,
        _mcp_base_url=f"http://127.0.0.1:{mcp_port}",
        auth=AuthConfig(
            enable_registration=True,
            expiration_hours=1,
            secret_key="test-secret-key-32-characters-long!!",
        ),
        ai=AiConfig(
            ocr=ModelConfig(provider="fake", model="fake-ocr-v1"),
            summary=ModelConfig(provider="fake", model="fake-summary-v1"),
            embedding=ModelConfig(provider="fake", model="fake-embedding-v1"),
        ),
    )


@pytest.fixture
async def create_test_user(
    user_service: UserService,
    test_users: list[str],
) -> None:
    """Register the default test user so the first user is bootstrapped as admin."""
    for test_user in test_users:
        await user_service.register(
            UserRegisterDTO(
                email=test_user,
                password=hashlib.md5(TEST_PASSWORD.encode("utf-8")).hexdigest(),
                user_name="Test User",
            )
        )


@pytest.fixture
def cli_env(
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    user_service: UserService,
    server_config: ServerConfig,
) -> CliServerEnv:
    """Provide a running Supernote server and pre-populate ~/.cache/supernote.pkl."""
    base_url = str(client.make_url("")).rstrip("/")
    admin_token = auth_headers["x-access-token"]
    cache_path = os.path.expanduser("~/.cache/supernote.pkl")
    FileCacheAuth(cache_path).save_credentials(admin_token, base_url)
    return CliServerEnv(
        url=base_url,
        client=client,
        session_manager=session_manager,
        user_service=user_service,
        server_config=server_config,
        admin_token=admin_token,
    )
