import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from supernote.server.config import ServerConfig, UserEntry, UsersConfig


@pytest.fixture(autouse=True)
def patch_server_config():
    """Override the autouse fixture from conftest.py to do nothing.

    This ensures that ServerConfig.load() runs the real logic instead of returning a mock.
    """
    yield


def test_server_config_defaults(tmp_path: Path) -> None:
    """Test loading configuration with defaults."""
    # Ensure no config file exists
    config_dir = tmp_path / "config"

    # Load config
    config = ServerConfig.load(config_dir)

    assert config.host == "0.0.0.0"
    assert config.port == 8080
    assert config.storage_dir == "storage"
    assert config.auth.secret_key != ""  # Should be generated

    # Check if secret was saved
    config_file = config_dir / "config.yaml"
    assert config_file.exists()
    with open(config_file) as f:
        data = yaml.safe_load(f)
        assert data["auth"]["secret_key"] == config.auth.secret_key


def test_server_config_load_from_file(tmp_path: Path) -> None:
    """Test loading configuration from a file."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "config.yaml"

    data = {
        "host": "127.0.0.1",
        "port": 9090,
        "auth": {"secret_key": "my-secret-key", "users_file": "my-users.yaml"},
    }
    with open(config_file, "w") as f:
        yaml.safe_dump(data, f)

    config = ServerConfig.load(config_dir)

    assert config.host == "127.0.0.1"
    assert config.port == 9090
    assert config.auth.secret_key == "my-secret-key"
    # Check path resolution
    assert config.auth.users_file == str(config_dir / "my-users.yaml")


def test_server_config_env_var_override(tmp_path: Path) -> None:
    """Test that environment variables override config file for secrets."""
    config_dir = tmp_path / "config"
    
    with patch.dict(os.environ, {"SUPERNOTE_JWT_SECRET": "env-secret"}):
        config = ServerConfig.load(config_dir)
        assert config.auth.secret_key == "env-secret"
        
        # Should save default config (empty secret) to file because file didn't exist
        config_file = config_dir / "config.yaml"
        assert config_file.exists()
        
        with open(config_file) as f:
            data = yaml.safe_load(f)
            # The saved secret should be empty because we didn't generate one
            # (since env var was provided) and we didn't save the env var.
            assert data["auth"]["secret_key"] == ""


def test_users_config_load_save(tmp_path: Path) -> None:
    """Test loading and saving users configuration."""
    users_file = tmp_path / "users.yaml"

    # 1. Load missing file (should return empty config)
    config = UsersConfig.load(users_file)
    assert config.users == []

    # 2. Add user and save
    user = UserEntry(username="test", password_md5="hash")
    config.users.append(user)
    config.save(users_file)

    assert users_file.exists()

    # 3. Load again
    config2 = UsersConfig.load(users_file)
    assert len(config2.users) == 1
    assert config2.users[0].username == "test"
    assert config2.users[0].password_md5 == "hash"


def test_users_config_corrupt_file(tmp_path: Path) -> None:
    """Test loading a corrupt users file."""
    users_file = tmp_path / "users.yaml"
    with open(users_file, "w") as f:
        f.write("invalid: yaml: [")

    config = UsersConfig.load(users_file)
    assert config.users == []
