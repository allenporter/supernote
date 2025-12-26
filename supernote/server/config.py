import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from mashumaro.mixins.dict import DataClassDictMixin

logger = logging.getLogger(__name__)


@dataclass
class AuthConfig(DataClassDictMixin):
    secret_key: str = ""
    expiration_hours: int = 24
    users_file: str = "users.yaml"


@dataclass
class UserEntry(DataClassDictMixin):
    username: str
    password_md5: str
    is_active: bool = True
    devices: list[str] = field(default_factory=list)
    profile: dict[str, Any] = field(default_factory=dict)
    mobile: str | None = None
    email: str | None = None
    avatar: str | None = None
    signature: str | None = None


@dataclass
class UsersConfig(DataClassDictMixin):
    users: list[UserEntry] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "UsersConfig":
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}
            return cls.from_dict(data)
        except Exception as e:
            logger.warning(f"Failed to load users file {path}: {e}")
            return cls()

    def save(self, path: str | Path) -> None:
        path = Path(path)
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.safe_dump(self.to_dict(), f, default_flow_style=False)


@dataclass
class ServerConfig(DataClassDictMixin):
    host: str = "0.0.0.0"
    port: int = 8080
    trace_log_file: str = "data/server_trace.log"
    storage_dir: str = "storage"
    auth: AuthConfig = field(default_factory=AuthConfig)

    @classmethod
    def load(cls, config_dir: str | Path | None = None) -> "ServerConfig":
        """Load configuration from directory."""
        # 1. Determine config directory
        if config_dir is None:
            config_dir = os.getenv("SUPERNOTE_CONFIG_DIR", "config")

        config_dir_path = Path(config_dir)
        config_file = config_dir_path / "config.yaml"

        # 2. Load from YAML if exists
        file_data: dict[str, Any] = {}
        if file_exists := config_file.exists():
            try:
                with open(config_file, "r") as f:
                    file_data = yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning(f"Failed to load config file {config_file}: {e}")

        # 3. Create config object using mashumaro
        try:
            config = cls.from_dict(file_data)
        except Exception as e:
            logger.warning(
                f"Failed to parse config file {config_file}, using defaults: {e}"
            )
            config = cls()

        # Resolve users_file relative to config_dir if it's just a filename (not already a path)
        users_path = Path(config.auth.users_file)
        if not users_path.is_absolute() and len(users_path.parts) == 1:
            config.auth.users_file = str(config_dir_path / users_path)

        # 4. Generate secret if missing AND not provided by env var
        env_secret = os.getenv("SUPERNOTE_JWT_SECRET")
        secret_generated = False

        if not config.auth.secret_key and not env_secret:
            logger.warning("No JWT secret key configured. Generating a new random key.")
            config.auth.secret_key = secrets.token_hex(32)
            secret_generated = True

        # 5. Save config if it was missing or if we generated a secret
        if not file_exists or secret_generated:
            try:
                # Ensure directory exists
                if not config_file.parent.exists():
                    config_file.parent.mkdir(parents=True, exist_ok=True)

                # Prepare config for saving (restore relative paths if possible)
                config_to_save = cls.from_dict(config.to_dict())
                try:
                    users_path_abs = Path(config.auth.users_file)
                    if users_path_abs.is_absolute() and users_path_abs.is_relative_to(
                        config_dir_path
                    ):
                        config_to_save.auth.users_file = str(
                            users_path_abs.relative_to(config_dir_path)
                        )
                except ValueError:
                    pass

                with open(config_file, "w") as f:
                    yaml.safe_dump(
                        config_to_save.to_dict(), f, default_flow_style=False
                    )

                if secret_generated:
                    logger.info(
                        f"Saved new configuration with generated secret to {config_file}"
                    )
                else:
                    logger.info(f"Created default configuration file at {config_file}")
            except Exception as e:
                logger.warning(f"Failed to save configuration to {config_file}: {e}")

        # 6. Apply env var override (runtime only, not saved)
        if env_secret:
            config.auth.secret_key = env_secret

        if os.getenv("SUPERNOTE_HOST"):
            config.host = os.getenv("SUPERNOTE_HOST", config.host)

        if os.getenv("SUPERNOTE_PORT"):
            try:
                config.port = int(os.getenv("SUPERNOTE_PORT", str(config.port)))
            except ValueError:
                pass

        if os.getenv("SUPERNOTE_STORAGE_DIR"):
            config.storage_dir = os.getenv("SUPERNOTE_STORAGE_DIR", config.storage_dir)

        return config
