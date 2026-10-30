import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from mashumaro.config import TO_DICT_ADD_OMIT_NONE_FLAG, BaseConfig
from mashumaro.mixins.yaml import DataClassYAMLMixin

logger = logging.getLogger(__name__)


def _get_bool_env(name: str, default: bool) -> bool:
    """Get a boolean value from an environment variable."""
    val = os.getenv(name)
    if val is None:
        return default
    return val.lower() in ("true", "1", "yes", "on")


@dataclass
class AuthConfig(DataClassYAMLMixin):
    """Authentication configuration."""

    secret_key: str = ""
    """JWT secret key.

    Env Var: `SUPERNOTE_JWT_SECRET`
    """

    expiration_hours: int = 24
    """JWT expiration time in hours."""

    device_expiration_hours: int = 87600
    """JWT expiration time for devices in hours (default: 10 years)."""

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
class WebhookEndpointConfig(DataClassYAMLMixin):
    """A single outbound webhook subscriber."""

    url: str = ""
    """The HTTP(S) endpoint that receives the webhook POST request."""

    user: str = ""
    """Email address of the user account whose events this endpoint receives."""

    secret: str = ""
    """Shared secret used to HMAC-SHA256 sign the payload.

    Never logged. Sent to receivers via the `X-Supernote-Signature` header so
    they can verify the payload was not tampered with in transit.
    """

    events: list[str] = field(default_factory=list)
    """Event names this endpoint wants to receive, e.g. `note.sync_completed`.

    If empty (the default), the endpoint receives every event for `user`.
    """

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError(
                f"Webhook endpoint URL must use http or https scheme with a valid host: {self.url!r}"
            )
        if not self.user or not self.user.strip():
            raise ValueError(
                "Webhook endpoint must specify a non-empty user email address."
            )

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class WebhookConfig(DataClassYAMLMixin):
    """Outbound webhook dispatch configuration."""

    enabled: bool = False
    """Whether outbound webhook dispatch is enabled.

    Env Var: `SUPERNOTE_WEBHOOKS_ENABLED`
    """

    endpoints: list[WebhookEndpointConfig] = field(default_factory=list)
    """Configured webhook subscribers."""

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
    """Backend implementation (`'gemini'`, `'openai'`, `'fake'`). Defaults to the entry's name.

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
    """Provider-specific model identifier (e.g. `'gemini-3.6-flash'`)."""

    max_concurrency: int = 5
    """Maximum number of concurrent requests allowed for this model."""

    def __post_init__(self) -> None:
        if not self.provider or not self.provider.strip():
            raise ValueError("ModelConfig must specify a non-empty provider.")
        if not self.model or not self.model.strip():
            raise ValueError("ModelConfig must specify a non-empty model.")
        if self.max_concurrency < 1:
            raise ValueError("ModelConfig max_concurrency must be >= 1.")

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

    def provider_type(self, name: str) -> str:
        """Return the backend implementation for the `ai.providers` entry `name`."""
        provider_cfg = self.providers.get(name)
        if provider_cfg is not None and provider_cfg.type:
            return provider_cfg.type
        return name

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

    mcp_enabled: bool = True
    """Whether to enable the Model Context Protocol (MCP) server and OAuth endpoints.

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

    trace_log_file: str | None = None
    """Path to trace log file.

    This will default to a file in the storage directory if unset.

    Env Var: `SUPERNOTE_TRACE_LOG_FILE`
    """

    trace_log_unsafe: bool = False
    """Whether to disable credential and token redaction in the trace log for debugging.

    Env Var: `SUPERNOTE_TRACE_LOG_UNSAFE`
    """

    storage_dir: str = "storage"
    """Directory for storing files and database.

    Env Var: `SUPERNOTE_STORAGE_DIR`
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

    gemini_ocr_model: str = "gemini-3.6-flash"
    """Legacy Gemini model to use for OCR and Summaries.

    Env Var: `SUPERNOTE_GEMINI_OCR_MODEL`
    """

    gemini_embedding_model: str = "gemini-embedding-001"
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

    metrics_enabled: bool = True
    """Whether to enable the Prometheus metrics endpoint and logging middleware.

    Env Var: `SUPERNOTE_METRICS_ENABLED`
    """

    metrics_path: str = "/metrics"
    """The path where Prometheus metrics are exposed.

    Env Var: `SUPERNOTE_METRICS_PATH`
    """

    webhooks: WebhookConfig = field(default_factory=WebhookConfig)
    """Outbound webhook dispatch configuration."""

    web_enabled: bool = True
    """Whether to serve the web frontend dashboard and static assets.

    Env Var: `SUPERNOTE_WEB_ENABLED`
    """

    web_notebook_preview: bool = True
    """Whether to generate and display notebook page previews in the web UI.

    When disabled, the web UI remains available for file, task, and metadata management,
    but skips CPU-heavy notebook rasterization.

    Env Var: `SUPERNOTE_WEB_NOTEBOOK_PREVIEW`
    """

    def __post_init__(self) -> None:
        self._sync_legacy_gemini_config()

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
        if config_file.exists():
            try:
                with open(config_file, "r") as f:
                    config = cls.from_yaml(f.read())
            except Exception as e:
                logger.warning(f"Failed to load config file {config_file}: {e}")

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
            logger.info(f"Metrics Enabled: {config.metrics_enabled}")

        if metrics_path := os.getenv("SUPERNOTE_METRICS_PATH"):
            config.metrics_path = metrics_path
            logger.info(f"Using SUPERNOTE_METRICS_PATH: {config.metrics_path}")

        if os.getenv("SUPERNOTE_WEBHOOKS_ENABLED"):
            config.webhooks.enabled = _get_bool_env(
                "SUPERNOTE_WEBHOOKS_ENABLED", config.webhooks.enabled
            )
            logger.info(f"Webhooks Enabled: {config.webhooks.enabled}")

        if os.getenv("SUPERNOTE_WEB_ENABLED"):
            config.web_enabled = _get_bool_env(
                "SUPERNOTE_WEB_ENABLED", config.web_enabled
            )
            logger.info(f"Web Enabled: {config.web_enabled}")

        if os.getenv("SUPERNOTE_WEB_NOTEBOOK_PREVIEW"):
            config.web_notebook_preview = _get_bool_env(
                "SUPERNOTE_WEB_NOTEBOOK_PREVIEW", config.web_notebook_preview
            )
            logger.info(f"Web Notebook Preview: {config.web_notebook_preview}")

        if trace_log_file := os.getenv("SUPERNOTE_TRACE_LOG_FILE"):
            config.trace_log_file = trace_log_file
            logger.info(f"Using SUPERNOTE_TRACE_LOG_FILE: {config.trace_log_file}")

        if os.getenv("SUPERNOTE_TRACE_LOG_UNSAFE"):
            config.trace_log_unsafe = _get_bool_env(
                "SUPERNOTE_TRACE_LOG_UNSAFE", config.trace_log_unsafe
            )
            logger.info(f"Trace Log Unsafe Mode: {config.trace_log_unsafe}")

        if config.trace_log_file is None:
            config.trace_log_file = str(
                Path(config.storage_dir) / "system" / "trace.log"
            )

        if not config_file.exists():
            logger.info(f"Saving config to {config_file}")
            config_file.parent.mkdir(parents=True, exist_ok=True)
            config_file.write_text(cast(str, config.to_yaml()))

        return config

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]
