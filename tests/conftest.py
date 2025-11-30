import pytest
from unittest.mock import patch
from pathlib import Path
import hashlib
import yaml
import jwt
from supernote.server.services.user import JWT_SECRET, JWT_ALGORITHM


@pytest.fixture(autouse=True)
def mock_storage(tmp_path: Path):
    storage_root = tmp_path / "storage"
    temp_root = tmp_path / "storage" / "temp"
    storage_root.mkdir(parents=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    # Create default folders
    (storage_root / "Note").mkdir()
    (storage_root / "Document").mkdir()
    (storage_root / "EXPORT").mkdir()

    with (
        patch("supernote.server.config.STORAGE_DIR", str(storage_root)),
        patch("supernote.server.config.TRACE_LOG_FILE", str(tmp_path / "trace.log")),
    ):
        yield storage_root


@pytest.fixture
def mock_users_file(tmp_path: Path):
    user = {
        "username": "test@example.com",
        "password_sha256": hashlib.sha256(b"testpassword").hexdigest(),
        "is_active": True,
    }
    users_file = tmp_path / "users.yaml"
    with open(users_file, "w") as f:
        yaml.safe_dump({"users": [user]}, f)
    yield str(users_file)


@pytest.fixture
def mock_trace_log(tmp_path: Path):
    log_file = tmp_path / "trace.log"
    with patch("supernote.server.config.TRACE_LOG_FILE", str(log_file)):
        yield str(log_file)


@pytest.fixture(name="auth_headers")
def auth_headers_fixture():
    token = jwt.encode({"sub": "test@example.com"}, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def patch_server_config(mock_trace_log, mock_users_file):
    with (
        patch("supernote.server.config.TRACE_LOG_FILE", mock_trace_log),
        patch("supernote.server.config.USER_CONFIG_FILE", mock_users_file),
    ):
        yield
