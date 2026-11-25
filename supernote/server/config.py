"""Typed server configuration models and environment variable resolution.

Defines `ServerConfig` along with nested configuration dataclasses (`AuthConfig`,
`AiConfig`, `ProviderConfig`, `ModelConfig`) serialized via `mashumaro` YAML mixins.

`ServerConfig.load` resolves settings in priority order:
1. `SUPERNOTE_*` environment variables (highest priority)
2. `config/config.yaml` (or `<SUPERNOTE_CONFIG_DIR>/config.yaml`)
3. Dataclass defaults and persistent SQLite coordination keys (fallback)

For a complete table of YAML keys and environment variables, see
`supernote.guides.configuration` and `supernote.guides.bootstrap_guide`.
"""

import copy
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from mashumaro.config import TO_DICT_ADD_OMIT_NONE_FLAG, BaseConfig
from mashumaro.mixins.yaml import DataClassYAMLMixin

from supernote.server.utils.image import DEFAULT_IMAGE_EXCLUDE_PATTERNS

logger = logging.getLogger(__name__)

VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
_COMPONENT_DOMAIN_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class ComponentConfigSource(StrEnum):
    """Origin tier for a component's effective configuration."""

    ENV = "env"
    YAML = "yaml"
    DATABASE = "database"
    DEFAULT = "default"

    @property
    def is_static(self) -> bool:
        """Whether this tier comes from static startup configuration (`env` or `yaml`)."""
        return self in (ComponentConfigSource.ENV, ComponentConfigSource.YAML)


def _normalize_log_level(level_name: str) -> str:
    """Validate and return an uppercase standard log level name."""
    normalized = level_name.strip().upper()
    if normalized not in VALID_LOG_LEVELS:
        raise ValueError(
            f"Invalid log level {level_name!r}; expected one of: "
            f"{', '.join(VALID_LOG_LEVELS)}"
        )
    return normalized


def _parse_bool(val: Any) -> bool:
    """Coerce a raw configuration or environment value to a boolean."""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes", "on")
    return bool(val)


def _get_bool_env(name: str, default: bool) -> bool:
    """Get a boolean value from an environment variable."""
    val = os.getenv(name)
    if val is None:
        return default
    return _parse_bool(val)


@dataclass
class AuthConfig(DataClassYAMLMixin):
    """Authentication configuration."""

    secret_key: str = ""
    """JWT secret key.

    Env Var: `SUPERNOTE_JWT_SECRET`
    """

    expiration_hours: int = 24
    """JWT expiration time in hours.

    Env Var: `SUPERNOTE_JWT_EXPIRATION_HOURS`
    """

    device_expiration_hours: int = 87600
    """JWT expiration time for devices in hours (default: 10 years).

    Env Var: `SUPERNOTE_DEVICE_EXPIRATION_HOURS`
    """

    enable_registration: bool = False
    """When disabled, registration is only allowed if there are no users in the system.

    Env Var: `SUPERNOTE_ENABLE_REGISTRATION`
    """

    enable_remote_password_reset: bool = False
    """When disabled, the public password reset endpoint returns 403.

    Env Var: `SUPERNOTE_ENABLE_REMOTE_PASSWORD_RESET`
    """

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class ProviderConfig(DataClassYAMLMixin):
    """Connection and authentication settings for an AI model provider."""

    api_key: str | None = None
    """API key for authenticating with the provider."""

    base_url: str | None = None
    """Optional custom base URL for the provider (e.g. local Ollama or vLLM server)."""

    type: str | None = None
    """Backend implementation (`'gemini'`, `'openai'`, `'apple'`, `'fake_ai'`). Defaults to the entry's name.

    Set it to configure several entries of one kind, e.g. two OpenAI-compatible
    servers named `ollama` and `llamacpp`.
    """

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class ModelConfig(DataClassYAMLMixin):
    """Configuration for a task-specific AI model (`ocr`, `summary`, `embedding`)."""

    provider: str = "gemini"
    """Name of the provider entry in `ai.providers` (e.g. `'gemini'`, `'openai'`, `'ollama'`)."""

    model: str = ""
    """Provider-specific model identifier (e.g. `'gemini-3.5-flash-lite'`)."""

    max_concurrency: int = 5
    """Maximum number of concurrent requests allowed for this model."""

    prompt_override: str | None = None
    """Optional fixed prompt that replaces the composed prompt for OCR models.

    Useful for dedicated OCR models (such as DeepSeek-OCR or GLM-OCR) trained
    on a single short instruction rather than the full metadata and legend prompt.
    """

    def __post_init__(self) -> None:
        if not self.provider or not self.provider.strip():
            raise ValueError("ModelConfig must specify a non-empty provider.")
        if not self.model or not self.model.strip():
            raise ValueError("ModelConfig must specify a non-empty model.")
        if self.max_concurrency < 1:
            raise ValueError("ModelConfig max_concurrency must be >= 1.")
        if self.prompt_override is not None and not self.prompt_override.strip():
            raise ValueError("ModelConfig prompt_override must be non-empty when set.")

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class AiConfig(DataClassYAMLMixin):
    """AI providers and per-capability model configuration."""

    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    """Configured AI providers keyed by provider name."""

    ocr: ModelConfig | None = None
    """Model configuration for page OCR extraction."""

    summary: ModelConfig | None = None
    """Model configuration for notebook summary generation."""

    embedding: ModelConfig | None = None
    """Model configuration for page embedding generation."""

    text: ModelConfig | None = None
    """Optional model configuration for structured JSON text generation (e.g. LLM wiki).

    Falls back to ``summary`` when unset.
    """

    @property
    def effective_text(self) -> ModelConfig | None:
        """Return ``text`` model configuration, falling back to ``summary`` when unset."""
        return self.text if self.text is not None else self.summary

    def provider_type(self, name: str) -> str:
        """Return the backend implementation for the `ai.providers` entry `name`."""
        provider_cfg = self.providers.get(name)
        if provider_cfg is not None and provider_cfg.type:
            return provider_cfg.type
        return name

    @property
    def active_provider_types(self) -> set[str]:
        """Return normalized backend provider types referenced by configured capability models."""
        return {
            self.provider_type(m.provider).strip().lower()
            for m in (self.ocr, self.summary, self.embedding, self.text)
            if m is not None
        }

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class ServerConfig(DataClassYAMLMixin):
    host: str = "0.0.0.0"
    """Host to bind the server to.

    Env Var: `SUPERNOTE_HOST`
    """

    port: int = 8080
    """Port to bind the server to.

    Env Var: `SUPERNOTE_PORT`
    """

    mcp_enabled: bool = field(
        default=True,
        metadata={"component": ("mcp", "enabled")},
    )
    """Whether to enable the Model Context Protocol (MCP) server and OAuth endpoints.

    Aliases `mcp.enabled`.

    Env Var: `SUPERNOTE_MCP_ENABLED`
    """

    mcp_port: int = 8081
    """Port to bind the MCP server to.

    Env Var: `SUPERNOTE_MCP_PORT`
    """

    _base_url: str | None = field(default=None, metadata={"name": "base_url"})
    """Base URL for the main server (port 8080).
    Used for generating links and for the MCP Authorization Server issuer.
    """

    _mcp_base_url: str | None = field(default=None, metadata={"name": "mcp_base_url"})
    """Base URL for the MCP server (port 8081).

    Used for RFC 9728 discovery if the server is behind a proxy.
    """

    log_level: str = "INFO"
    """Server logging level (DEBUG, INFO, WARNING, ERROR).

    Env Var: `SUPERNOTE_LOG_LEVEL`
    """

    trace_log_file: str | None = None
    """Path to trace log file.

    This will default to a file in the storage directory if unset.

    Env Var: `SUPERNOTE_TRACE_LOG_FILE`
    """

    trace_log_unsafe: bool = False
    """Whether to disable credential and token redaction across trace and access logs.

    Env Var: `SUPERNOTE_TRACE_LOG_UNSAFE`
    """

    storage_dir: str = "storage"
    """Directory for storing files and database.

    Env Var: `SUPERNOTE_STORAGE_DIR`
    """

    default_user_quota: int = 0
    """Default per-user storage quota in bytes (0 = unlimited, bounded by storage volume free space).

    Individual users can override this via `UserDO.total_capacity` (`supernote admin user set-quota`).

    Env Var: `SUPERNOTE_DEFAULT_USER_QUOTA`
    """

    # TODO(#403): Revisit per-format image_* config fields alongside declarative
    # path/extension processing and prompt routing so both share one config model.
    enable_image_processing: bool = True
    """Whether standalone raster images (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`) are indexed by the background OCR pipeline."""

    image_include_patterns: list[str] = field(default_factory=list)
    """Optional VFS path globs restricting standalone image indexing (empty = allow all paths not excluded)."""

    image_exclude_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_IMAGE_EXCLUDE_PATTERNS)
    )
    """VFS path globs excluded from standalone image indexing (defaults to `MyStyle/**` and `EXPORT/**`)."""

    event_log_retention_days: int = field(
        default=90,
        metadata={"component": ("events", "retention_days")},
    )
    """Number of days to retain domain events in `f_user_event` (0 = retain indefinitely).

    Aliases `events.retention_days`.

    Env Var: `SUPERNOTE_EVENT_LOG_RETENTION_DAYS`
    """

    proxy_mode: str | None = None
    """Proxy header handling mode: None/'disabled' (ignore proxy headers), 'relaxed' (trust immediate upstream), or 'strict' (require specific trusted IPs). Defaults to None for security.

    Env Var: `SUPERNOTE_PROXY_MODE`
    """

    trusted_proxies: list[str] = field(
        default_factory=lambda: ["127.0.0.1", "::1", "172.17.0.0/16"]
    )
    """List of trusted proxy IPs/networks (used in strict mode). Supports CIDR notation.

    Env Var: `SUPERNOTE_TRUSTED_PROXIES` (comma-separated)
    """

    auth: AuthConfig = field(default_factory=AuthConfig)

    ai: AiConfig = field(default_factory=AiConfig)
    """Structured AI providers and per-capability model configuration."""

    gemini_api_key: str | None = None
    """Legacy Google Gemini API Key for OCR, Summaries, and Embeddings.

    Prefer configuring `ai.providers.gemini` and `ai.{ocr,summary,embedding}`.

    Env Var: `SUPERNOTE_GEMINI_API_KEY`
    """

    gemini_ocr_model: str = "gemini-3.5-flash-lite"
    """Legacy Gemini model to use for OCR and Summaries.

    Env Var: `SUPERNOTE_GEMINI_OCR_MODEL`
    """

    gemini_embedding_model: str = "gemini-embedding-2"
    """Legacy Gemini model to use for Embeddings.

    Env Var: `SUPERNOTE_GEMINI_EMBEDDING_MODEL`
    """

    gemini_max_concurrency: int = 5
    """Legacy maximum number of concurrent Gemini API calls.

    Env Var: `SUPERNOTE_GEMINI_MAX_CONCURRENCY`
    """

    prompts_dir: str | None = None
    """Directory where custom AI prompts are located.

    Env Var: `SUPERNOTE_PROMPTS_DIR`
    """

    metrics_enabled: bool = field(
        default=True,
        metadata={"component": ("metrics", "enabled")},
    )
    """Whether to enable the Prometheus metrics endpoint and logging middleware.

    Aliases `metrics.enabled`.

    Env Var: `SUPERNOTE_METRICS_ENABLED`
    """

    metrics_path: str = field(
        default="/metrics",
        metadata={"component": ("metrics", "path")},
    )
    """The path where Prometheus metrics are exposed.

    Aliases `metrics.path`.

    Env Var: `SUPERNOTE_METRICS_PATH`
    """

    webhooks: dict[str, Any] = field(
        default_factory=dict,
        metadata={"component": "webhooks"},
    )
    """Raw configuration section for the outbound webhooks component."""

    wiki: dict[str, Any] = field(
        default_factory=dict,
        metadata={"component": "wiki"},
    )
    """Raw configuration section for the opt-in LLM wiki component."""

    web_enabled: bool = field(
        default=True,
        metadata={"component": ("web_ui", "enabled")},
    )
    """Whether to serve the web frontend dashboard and static assets.

    Aliases `web_ui.enabled`.

    Env Var: `SUPERNOTE_WEB_ENABLED`
    """

    web_notebook_preview: bool = True
    """Whether to generate and display notebook page previews in the web UI.

    When disabled, the web UI remains available for file, task, and metadata management,
    but skips CPU-heavy notebook rasterization.

    Env Var: `SUPERNOTE_WEB_NOTEBOOK_PREVIEW`
    """

    def __post_init__(self) -> None:
        self.log_level = _normalize_log_level(self.log_level)
        if isinstance(self.default_user_quota, bool) or self.default_user_quota < 0:
            raise ValueError("default_user_quota must be a non-negative integer")
        if self.event_log_retention_days < 0:
            raise ValueError("event_log_retention_days must be >= 0")
        self._root_component_configs: dict[str, dict[str, Any]] = {}
        self._component_sources: dict[str, ComponentConfigSource] = {}
        self._sync_legacy_gemini_config()
        self._seed_programmatic_component_sources()

    def _seed_programmatic_component_sources(self) -> None:
        """Record `ComponentConfigSource.YAML` provenance when `ServerConfig` is constructed with non-default component fields."""
        for f in fields(self):
            comp_meta = f.metadata.get("component")
            if isinstance(comp_meta, str):
                if getattr(self, f.name):
                    self._component_sources.setdefault(
                        comp_meta, ComponentConfigSource.YAML
                    )
            elif isinstance(comp_meta, tuple):
                domain, _ = comp_meta
                if getattr(self, f.name) != f.default:
                    self._component_sources.setdefault(
                        domain, ComponentConfigSource.YAML
                    )
        if self.ai.active_provider_types:
            self._component_sources.setdefault("ai", ComponentConfigSource.YAML)

    @property
    def root_component_configs(self) -> Mapping[str, dict[str, Any]]:
        """Root-level `<domain>:` sections loaded from `config.yaml`."""
        return {
            domain: copy.deepcopy(cfg)
            for domain, cfg in self._root_component_configs.items()
        }

    @property
    def component_sources(self) -> Mapping[str, ComponentConfigSource]:
        """Static configuration source (`ENV` or `YAML`) recorded per component domain."""
        return dict(self._component_sources)

    def _sync_legacy_gemini_config(self) -> None:
        """Synchronize legacy top-level `gemini_*` fields with `self.ai`."""
        if not self.gemini_api_key or not self.gemini_api_key.strip():
            return
        gemini_provider = self.ai.providers.setdefault("gemini", ProviderConfig())
        if not gemini_provider.api_key:
            gemini_provider.api_key = self.gemini_api_key
        if (
            self.ai.ocr is None
            and self.ai.summary is None
            and self.ai.embedding is None
        ):
            self.ai.ocr = ModelConfig(
                provider="gemini",
                model=self.gemini_ocr_model,
                max_concurrency=self.gemini_max_concurrency,
            )
            self.ai.summary = ModelConfig(
                provider="gemini",
                model=self.gemini_ocr_model,
                max_concurrency=self.gemini_max_concurrency,
            )
            self.ai.embedding = ModelConfig(
                provider="gemini",
                model=self.gemini_embedding_model,
                max_concurrency=self.gemini_max_concurrency,
            )

    @property
    def configured_base_url(self) -> str | None:
        """Get the explicitly configured base URL, or None if unset.

        Returns `None` when `SUPERNOTE_BASE_URL` (config `base_url`) is not set,
        allowing callers to fall back to the incoming request's base URL.

        Env Var: `SUPERNOTE_BASE_URL`
        """
        if self._base_url:
            return self._base_url.rstrip("/")
        return None

    @property
    def base_url(self) -> str:
        """Get the base URL for the main server.

        Falls back to the configured host/port when `SUPERNOTE_BASE_URL` is unset.

        Env Var: `SUPERNOTE_BASE_URL`
        """
        if self.configured_base_url is not None:
            return self.configured_base_url
        host = "localhost" if self.host == "0.0.0.0" else self.host
        return f"http://{host}:{self.port}"

    @property
    def mcp_base_url(self) -> str:
        """Get the base URL for the MCP server.

        Env Var: `SUPERNOTE_MCP_BASE_URL`
        """
        if self._mcp_base_url:
            return self._mcp_base_url.rstrip("/")
        host = "localhost" if self.host == "0.0.0.0" else self.host
        return f"http://{host}:{self.mcp_port}"

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.storage_dir}/system/supernote.db"

    @property
    def storage_root(self) -> Path:
        return Path(self.storage_dir)

    @property
    def ephemeral(self) -> bool:
        """Whether the server is running in ephemeral mode."""
        return _get_bool_env("SUPERNOTE_EPHEMERAL", False)

    @classmethod
    def load(
        cls, config_dir: str | Path | None = None, config_file: str | Path | None = None
    ) -> "ServerConfig":
        """Load configuration from directory. READ-ONLY."""
        if config_file is not None:
            config_file = Path(config_file)
        else:
            if config_dir is None:
                config_dir = os.getenv("SUPERNOTE_CONFIG_DIR", "config")
                logger.info(f"Using SUPERNOTE_CONFIG_DIR: {config_dir}")
            config_dir_path = Path(config_dir)
            config_file = config_dir_path / "config.yaml"
            logger.info(f"Using config file: {config_file}")

        config = cls()
        raw_yaml_data: dict[str, Any] = {}
        if config_file.exists():
            try:
                raw_text = config_file.read_text()
                parsed_yaml = yaml.safe_load(raw_text)
                if isinstance(parsed_yaml, dict):
                    raw_yaml_data = parsed_yaml
                config = cls.from_yaml(raw_text)
            except Exception as e:
                logger.warning(f"Failed to load config file {config_file}: {e}")

        config._component_sources.clear()
        alias_by_target: dict[tuple[str, str], str] = {
            comp_meta: f.name
            for f in fields(cls)
            if isinstance((comp_meta := f.metadata.get("component")), tuple)
        }
        for key, value in raw_yaml_data.items():
            if (
                isinstance(key, str)
                and _COMPONENT_DOMAIN_RE.fullmatch(key)
                and key not in ("ai", "auth")
                and isinstance(value, dict)
            ):
                if "enabled" in value:
                    value = {**value, "enabled": _parse_bool(value["enabled"])}
                config._root_component_configs[key] = copy.deepcopy(value)
                config._component_sources[key] = ComponentConfigSource.YAML
                logger.debug(
                    "Loaded root YAML component section for %r (keys=%s)",
                    key,
                    sorted(value.keys()),
                )
                for sub_key, sub_val in value.items():
                    if (attr_name := alias_by_target.get((key, sub_key))) is not None:
                        setattr(config, attr_name, sub_val)

        for f in fields(cls):
            if f.name in raw_yaml_data:
                comp_meta = f.metadata.get("component")
                if isinstance(comp_meta, tuple):
                    config._component_sources[comp_meta[0]] = ComponentConfigSource.YAML
        if "ai" in raw_yaml_data or "gemini_api_key" in raw_yaml_data:
            config._component_sources["ai"] = ComponentConfigSource.YAML

        # 4. JWT Secret priority: Env > Config > Database (CoordinationService)
        env_secret = os.getenv("SUPERNOTE_JWT_SECRET")
        if env_secret:
            logger.info("Using SUPERNOTE_JWT_SECRET")
            config.auth.secret_key = env_secret

        if not config.auth.secret_key:
            logger.info(
                "No JWT secret key configured; will use persistent database key."
            )

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

        if os.getenv("SUPERNOTE_MCP_ENABLED"):
            config.mcp_enabled = _get_bool_env(
                "SUPERNOTE_MCP_ENABLED", config.mcp_enabled
            )
            config._component_sources["mcp"] = ComponentConfigSource.ENV
            logger.info(f"MCP Enabled: {config.mcp_enabled}")

        if os.getenv("SUPERNOTE_MCP_PORT"):
            try:
                config.mcp_port = int(
                    os.getenv("SUPERNOTE_MCP_PORT", str(config.mcp_port))
                )
                logger.info(f"Using SUPERNOTE_MCP_PORT: {config.mcp_port}")
            except ValueError:
                pass

        if os.getenv("SUPERNOTE_STORAGE_DIR"):
            config.storage_dir = os.getenv("SUPERNOTE_STORAGE_DIR", config.storage_dir)
            logger.info(f"Using SUPERNOTE_STORAGE_DIR: {config.storage_dir}")

        if (raw_quota := os.getenv("SUPERNOTE_DEFAULT_USER_QUOTA")) is not None:
            try:
                quota_val = int(raw_quota)
                if quota_val < 0:
                    raise ValueError("must be >= 0")
                config.default_user_quota = quota_val
                logger.info(
                    f"Using SUPERNOTE_DEFAULT_USER_QUOTA: {config.default_user_quota}"
                )
            except ValueError as err:
                logger.warning(
                    f"Ignoring invalid SUPERNOTE_DEFAULT_USER_QUOTA {raw_quota!r}: {err}"
                )

        if (
            raw_retention := os.getenv("SUPERNOTE_EVENT_LOG_RETENTION_DAYS")
        ) is not None:
            try:
                retention_val = int(raw_retention)
                if retention_val < 0:
                    raise ValueError("must be >= 0")
                config.event_log_retention_days = retention_val
                config._component_sources["events"] = ComponentConfigSource.ENV
                logger.info(
                    f"Using SUPERNOTE_EVENT_LOG_RETENTION_DAYS: {config.event_log_retention_days}"
                )
            except ValueError as err:
                logger.warning(
                    f"Ignoring invalid SUPERNOTE_EVENT_LOG_RETENTION_DAYS {raw_retention!r}: {err}"
                )

        if os.getenv("SUPERNOTE_BASE_URL"):
            config._base_url = os.getenv("SUPERNOTE_BASE_URL")
            logger.info(f"Using SUPERNOTE_BASE_URL: {config._base_url}")

        if os.getenv("SUPERNOTE_MCP_BASE_URL"):
            config._mcp_base_url = os.getenv("SUPERNOTE_MCP_BASE_URL")
            logger.info(f"Using SUPERNOTE_MCP_BASE_URL: {config._mcp_base_url}")

        # Legacy support/compatibility if USER sets SUPERNOTE_AUTH_URL_BASE
        if os.getenv("SUPERNOTE_AUTH_URL_BASE"):
            if not config._base_url:
                config._base_url = os.getenv("SUPERNOTE_AUTH_URL_BASE")
                logger.info(
                    f"Using legacy SUPERNOTE_AUTH_URL_BASE as base_url: {config._base_url}"
                )

        if os.getenv("SUPERNOTE_ENABLE_REGISTRATION"):
            config.auth.enable_registration = _get_bool_env(
                "SUPERNOTE_ENABLE_REGISTRATION", config.auth.enable_registration
            )
            logger.info(f"Registration Enabled: {config.auth.enable_registration}")

        if os.getenv("SUPERNOTE_ENABLE_REMOTE_PASSWORD_RESET"):
            config.auth.enable_remote_password_reset = _get_bool_env(
                "SUPERNOTE_ENABLE_REMOTE_PASSWORD_RESET",
                config.auth.enable_remote_password_reset,
            )
            logger.info(
                f"Remote Password Reset Enabled: {config.auth.enable_remote_password_reset}"
            )

        if raw_exp := os.getenv("SUPERNOTE_JWT_EXPIRATION_HOURS"):
            try:
                exp_val = int(raw_exp)
                if exp_val > 0:
                    config.auth.expiration_hours = exp_val
                    logger.info(
                        f"Using SUPERNOTE_JWT_EXPIRATION_HOURS: {config.auth.expiration_hours}"
                    )
            except ValueError:
                pass

        if raw_dev_exp := os.getenv("SUPERNOTE_DEVICE_EXPIRATION_HOURS"):
            try:
                dev_exp_val = int(raw_dev_exp)
                if dev_exp_val > 0:
                    config.auth.device_expiration_hours = dev_exp_val
                    logger.info(
                        f"Using SUPERNOTE_DEVICE_EXPIRATION_HOURS: {config.auth.device_expiration_hours}"
                    )
            except ValueError:
                pass

        if os.getenv("SUPERNOTE_PROXY_MODE"):
            config.proxy_mode = os.getenv("SUPERNOTE_PROXY_MODE")
            logger.info(f"Using SUPERNOTE_PROXY_MODE: {config.proxy_mode}")

        if os.getenv("SUPERNOTE_TRUSTED_PROXIES"):
            val = os.getenv("SUPERNOTE_TRUSTED_PROXIES", "")
            config.trusted_proxies = [p.strip() for p in val.split(",") if p.strip()]
            logger.info(f"Using SUPERNOTE_TRUSTED_PROXIES: {config.trusted_proxies}")

        if gemini_api_key := os.getenv("SUPERNOTE_GEMINI_API_KEY"):
            config.gemini_api_key = gemini_api_key
            config.ai.providers.setdefault(
                "gemini", ProviderConfig()
            ).api_key = gemini_api_key
            config._component_sources["gemini"] = ComponentConfigSource.ENV
            logger.info(
                f"Using SUPERNOTE_GEMINI_API_KEY: xxx...{config.gemini_api_key[-3:]}"
            )

        if gemini_ocr_model := os.getenv("SUPERNOTE_GEMINI_OCR_MODEL"):
            config.gemini_ocr_model = gemini_ocr_model
            if config.ai.ocr and config.ai.ocr.provider == "gemini":
                config.ai.ocr.model = gemini_ocr_model
            if config.ai.summary and config.ai.summary.provider == "gemini":
                config.ai.summary.model = gemini_ocr_model
            logger.info(f"Using SUPERNOTE_GEMINI_OCR_MODEL: {config.gemini_ocr_model}")

        if gemini_embedding_model := os.getenv("SUPERNOTE_GEMINI_EMBEDDING_MODEL"):
            config.gemini_embedding_model = gemini_embedding_model
            if config.ai.embedding and config.ai.embedding.provider == "gemini":
                config.ai.embedding.model = gemini_embedding_model
            logger.info(
                f"Using SUPERNOTE_GEMINI_EMBEDDING_MODEL: {config.gemini_embedding_model}"
            )

        if gemini_max_concurrency := os.getenv("SUPERNOTE_GEMINI_MAX_CONCURRENCY"):
            try:
                config.gemini_max_concurrency = int(gemini_max_concurrency)
                for model_cfg in (
                    config.ai.ocr,
                    config.ai.summary,
                    config.ai.embedding,
                ):
                    if model_cfg and model_cfg.provider == "gemini":
                        model_cfg.max_concurrency = config.gemini_max_concurrency
                logger.info(
                    f"Using SUPERNOTE_GEMINI_MAX_CONCURRENCY: {config.gemini_max_concurrency}"
                )
            except ValueError:
                pass

        config._sync_legacy_gemini_config()

        if prompts_dir := os.getenv("SUPERNOTE_PROMPTS_DIR"):
            config.prompts_dir = prompts_dir
            logger.info(f"Using SUPERNOTE_PROMPTS_DIR: {config.prompts_dir}")

        if os.getenv("SUPERNOTE_METRICS_ENABLED"):
            config.metrics_enabled = _get_bool_env(
                "SUPERNOTE_METRICS_ENABLED", config.metrics_enabled
            )
            config._component_sources["metrics"] = ComponentConfigSource.ENV
            logger.info(f"Metrics Enabled: {config.metrics_enabled}")

        if metrics_path := os.getenv("SUPERNOTE_METRICS_PATH"):
            config.metrics_path = metrics_path
            config._component_sources["metrics"] = ComponentConfigSource.ENV
            logger.info(f"Using SUPERNOTE_METRICS_PATH: {config.metrics_path}")

        if os.getenv("SUPERNOTE_WEBHOOKS_ENABLED"):
            config.webhooks["enabled"] = _get_bool_env(
                "SUPERNOTE_WEBHOOKS_ENABLED",
                bool(config.webhooks.get("enabled", False)),
            )
            config._component_sources["webhooks"] = ComponentConfigSource.ENV
            logger.info(f"Webhooks Enabled: {config.webhooks['enabled']}")

        if os.getenv("SUPERNOTE_WIKI_ENABLED"):
            config.wiki["enabled"] = _get_bool_env(
                "SUPERNOTE_WIKI_ENABLED",
                bool(config.wiki.get("enabled", False)),
            )
            config._component_sources["wiki"] = ComponentConfigSource.ENV
            logger.info(f"Wiki Enabled: {config.wiki['enabled']}")

        if os.getenv("SUPERNOTE_WEB_ENABLED"):
            config.web_enabled = _get_bool_env(
                "SUPERNOTE_WEB_ENABLED", config.web_enabled
            )
            config._component_sources["web_ui"] = ComponentConfigSource.ENV
            logger.info(f"Web Enabled: {config.web_enabled}")

        if os.getenv("SUPERNOTE_WEB_NOTEBOOK_PREVIEW"):
            config.web_notebook_preview = _get_bool_env(
                "SUPERNOTE_WEB_NOTEBOOK_PREVIEW", config.web_notebook_preview
            )
            logger.info(f"Web Notebook Preview: {config.web_notebook_preview}")

        if raw_log_level := os.getenv("SUPERNOTE_LOG_LEVEL"):
            config.log_level = _normalize_log_level(raw_log_level)
            logger.info(f"Using SUPERNOTE_LOG_LEVEL: {config.log_level}")

        if (trace_log_file := os.getenv("SUPERNOTE_TRACE_LOG_FILE")) is not None:
            config.trace_log_file = trace_log_file
            logger.info(f"Using SUPERNOTE_TRACE_LOG_FILE: {config.trace_log_file!r}")

        if os.getenv("SUPERNOTE_TRACE_LOG_UNSAFE"):
            config.trace_log_unsafe = _get_bool_env(
                "SUPERNOTE_TRACE_LOG_UNSAFE", config.trace_log_unsafe
            )
            logger.info(f"Trace Log Unsafe Mode: {config.trace_log_unsafe}")

        if config.trace_log_file is None:
            config.trace_log_file = str(
                Path(config.storage_dir) / "system" / "trace.log"
            )

        return config

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]
