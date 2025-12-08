"""Shared pytest fixtures for server tests.

This module is automatically discovered by pytest as a plugin.
"""

import hashlib
from collections.abc import Generator
from pathlib import Path
from typing import Awaitable, Callable
from unittest.mock import patch

import jwt
import pytest
import yaml
from aiohttp.test_utils import TestClient
from aiohttp.web import Application

from supernote.server.services.user import JWT_ALGORITHM, JWT_SECRET

# Shared test constants - import these in test files instead of redefining
TEST_USERNAME = "test@example.com"
TEST_PASSWORD = "testpassword"

# Type alias for the aiohttp_client fixture - import this in test files
AiohttpClient = Callable[[Application], Awaitable[TestClient]]


@pytest.fixture
def mock_users_file(tmp_path: Path) -> Generator[str, None, None]:
    """Create a temporary users.yaml file for testing."""
    user = {
        "username": TEST_USERNAME,
        "password_md5": hashlib.md5(TEST_PASSWORD.encode("utf-8")).hexdigest(),
        "is_active": True,
    }
    users_file = tmp_path / "users.yaml"
    with open(users_file, "w") as f:
        yaml.safe_dump({"users": [user]}, f)
    yield str(users_file)


@pytest.fixture
def mock_trace_log(tmp_path: Path) -> Generator[str, None, None]:
    """Create a temporary trace log file for testing."""
    log_file = tmp_path / "trace.log"
    with patch("supernote.server.config.TRACE_LOG_FILE", str(log_file)):
        yield str(log_file)


@pytest.fixture(name="auth_headers")
def auth_headers_fixture() -> dict[str, str]:
    """Generate auth headers with a valid JWT token."""
    token = jwt.encode({"sub": TEST_USERNAME}, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {"x-access-token": token}


@pytest.fixture(autouse=True)
def patch_server_config(
    mock_trace_log: str, mock_users_file: str, tmp_path: Path
) -> Generator[None, None, None]:
    """Automatically patch server config for all server tests."""
    storage_dir = tmp_path / "storage_test"
    with (
        patch("supernote.server.config.TRACE_LOG_FILE", mock_trace_log),
        patch("supernote.server.config.USER_CONFIG_FILE", mock_users_file),
        patch("supernote.server.config.STORAGE_DIR", str(storage_dir)),
    ):
        yield
