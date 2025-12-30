"""Shared pytest fixtures for server tests.

This module is automatically discovered by pytest as a plugin.
"""

import hashlib
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import jwt
import pytest

from supernote.server.config import AuthConfig, ServerConfig, UserEntry
from supernote.server.services.state import StateService
from supernote.server.services.user import JWT_ALGORITHM
from tests.conftest import TEST_PASSWORD, TEST_USERNAME


@pytest.fixture
def mock_trace_log(tmp_path: Path) -> Generator[str, None, None]:
    """Create a temporary trace log file for testing."""
    log_file = tmp_path / "trace.log"
    yield str(log_file)


@pytest.fixture
def server_config(mock_trace_log: str, mock_storage: Path) -> ServerConfig:
    """Create a ServerConfig object for testing."""
    test_user = UserEntry(
        username=TEST_USERNAME,
        password_md5=hashlib.md5(TEST_PASSWORD.encode("utf-8")).hexdigest(),
        is_active=True,
        display_name="Test User",
    )

    return ServerConfig(
        trace_log_file=mock_trace_log,
        storage_dir=str(mock_storage),
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


@pytest.fixture(name="auth_headers")
def auth_headers_fixture(
    server_config: ServerConfig, state_service: StateService
) -> dict[str, str]:
    """Generate auth headers and persist session in state."""
    secret = server_config.auth.secret_key
    token = jwt.encode({"sub": TEST_USERNAME}, secret, algorithm=JWT_ALGORITHM)
    state_service.create_session(token, TEST_USERNAME)
    return {"x-access-token": token}
