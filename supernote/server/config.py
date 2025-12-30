import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from mashumaro.config import TO_DICT_ADD_OMIT_NONE_FLAG, BaseConfig
from mashumaro.mixins.yaml import DataClassYAMLMixin

logger = logging.getLogger(__name__)


@dataclass
class AuthConfig(DataClassYAMLMixin):
    secret_key: str = ""
    expiration_hours: int = 24
    users: list["UserEntry"] = field(default_factory=list)

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class UserEntry(DataClassYAMLMixin):
    username: str
    password_md5: str
    is_active: bool = True
    display_name: str | None = None
    email: str | None = None
    phone: str | None = None
    avatar: str | None = None
    total_capacity: str = "25485312"

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class ServerConfig(DataClassYAMLMixin):
    host: str = "0.0.0.0"
    port: int = 8080
    trace_log_file: str | None = None
    storage_dir: str = "storage"
    auth: AuthConfig = field(default_factory=AuthConfig)

    @classmethod
    def load(cls, config_dir: str | Path | None = None) -> "ServerConfig":
        """Load configuration from directory. READ-ONLY."""
        if config_dir is None:
            config_dir = os.getenv("SUPERNOTE_CONFIG_DIR", "config")

        config_dir_path = Path(config_dir)
        config_file = config_dir_path / "config.yaml"

        config = cls()
        if config_file.exists():
            try:
                with open(config_file, "r") as f:
                    config = cls.from_yaml(f.read())
            except Exception as e:
                logger.warning(f"Failed to load config file {config_file}: {e}")

        # 4. JWT Secret priority: Env > Config > Random(in-memory only)
        env_secret = os.getenv("SUPERNOTE_JWT_SECRET")
        if env_secret:
            logger.info("Using SUPERNOTE_JWT_SECRET")
            config.auth.secret_key = env_secret

        if not config.auth.secret_key:
            logger.warning(
                "No JWT secret key configured. Using a temporary in-memory key."
            )
            config.auth.secret_key = secrets.token_hex(32)

        # Apply other env var overrides
        if os.getenv("SUPERNOTE_HOST"):
            config.host = os.getenv("SUPERNOTE_HOST", config.host)
            logger.info(f"Using SUPERNOTE_HOST: {config.host}")

        if os.getenv("SUPERNOTE_PORT"):
            try:
                config.port = int(os.getenv("SUPERNOTE_PORT", str(config.port)))
                logger.info(f"Using SUPERNOTE_PORT: {config.port}")
            except ValueError:
                pass

        if os.getenv("SUPERNOTE_STORAGE_DIR"):
            config.storage_dir = os.getenv("SUPERNOTE_STORAGE_DIR", config.storage_dir)
            logger.info(f"Using SUPERNOTE_STORAGE_DIR: {config.storage_dir}")

        return config

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]
