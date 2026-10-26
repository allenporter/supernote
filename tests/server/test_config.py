import os
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from supernote.server.config import (
    AiConfig,
    ModelConfig,
    ProviderConfig,
    ServerConfig,
    WebhookEndpointConfig,
)


@pytest.fixture(autouse=True)
def patch_server_config() -> Generator[None]:
    """Override the autouse fixture from conftest.py to do nothing.

    This ensures that ServerConfig.load() runs the real logic instead of returning a mock.
    """
    yield


def test_server_config_defaults(tmp_path: Path) -> None:
    """Test loading configuration with defaults (does not write config.yaml to disk)."""
    config_dir = tmp_path / "config"
    config = ServerConfig.load(config_dir)

    assert config.host == "0.0.0.0"
    assert config.port == 8080
    assert config.storage_dir == "storage"
    assert config.auth.secret_key == ""
    assert not (config_dir / "config.yaml").exists()


def test_server_config_load_from_file(tmp_path: Path) -> None:
    """Test loading configuration from a file including users."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "config.yaml"

    data = {
        "host": "127.0.0.1",
        "port": 9090,
        "auth": {
            "secret_key": "my-secret-key",
            "enable_registration": True,
        },
    }
    with open(config_file, "w") as f:
        yaml.safe_dump(data, f)

    config = ServerConfig.load(config_dir)

    assert config.host == "127.0.0.1"
    assert config.port == 9090
    assert config.auth.secret_key == "my-secret-key"
    assert config.auth.enable_registration is True


def test_server_config_env_var_override(tmp_path: Path) -> None:
    """Test that environment variables override config file."""
    config_dir = tmp_path / "config"
    with patch.dict(
        os.environ,
        {
            "SUPERNOTE_JWT_SECRET": "env-secret",
            "SUPERNOTE_HOST": "1.2.3.4",
            "SUPERNOTE_PORT": "5555",
        },
    ):
        config = ServerConfig.load(config_dir)
        assert config.auth.secret_key == "env-secret"
        assert config.host == "1.2.3.4"
        assert config.port == 5555


def test_example_config_is_valid() -> None:
    """Ensure config-example.yaml can be loaded by ServerConfig."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    config_path = os.path.join(base_dir, "config-example.yaml")

    config = ServerConfig.load(config_file=config_path)

    assert config.host == "0.0.0.0"
    assert config.port == 8080
    assert config.storage_dir == "storage"
    assert config.auth.secret_key == "CHANGE_ME_TO_A_SECURE_RANDOM_STRING"
    assert config.auth.enable_registration is False


def test_configured_base_url_none_when_unset() -> None:
    """configured_base_url returns None when SUPERNOTE_BASE_URL is not set."""
    config = ServerConfig()
    assert config.configured_base_url is None


def test_configured_base_url_strips_trailing_slash() -> None:
    """configured_base_url returns the configured URL without a trailing slash."""
    config = ServerConfig(_base_url="https://notes.example.com/")
    assert config.configured_base_url == "https://notes.example.com"


def test_base_url_uses_configured_value() -> None:
    """base_url uses the configured base URL when set."""
    config = ServerConfig(_base_url="https://notes.example.com/")
    assert config.base_url == "https://notes.example.com"


def test_base_url_falls_back_to_host_and_port() -> None:
    """base_url falls back to host:port when SUPERNOTE_BASE_URL is unset."""
    config = ServerConfig(host="127.0.0.1", port=9090)
    assert config.configured_base_url is None
    assert config.base_url == "http://127.0.0.1:9090"


def test_base_url_fallback_maps_wildcard_host_to_localhost() -> None:
    """base_url fallback maps the 0.0.0.0 wildcard host to localhost."""
    config = ServerConfig(host="0.0.0.0", port=8080)
    assert config.base_url == "http://localhost:8080"


def test_configured_base_url_from_env(tmp_path: Path) -> None:
    """configured_base_url reflects SUPERNOTE_BASE_URL from the environment."""
    config_dir = tmp_path / "config"
    with patch.dict(os.environ, {"SUPERNOTE_BASE_URL": "https://env.example.com/"}):
        config = ServerConfig.load(config_dir)
        assert config.configured_base_url == "https://env.example.com"
        assert config.base_url == "https://env.example.com"


def test_server_config_webhooks_default_disabled(tmp_path: Path) -> None:
    """Webhooks are disabled with no endpoints by default."""
    config_dir = tmp_path / "config"
    config = ServerConfig.load(config_dir)

    assert config.webhooks.enabled is False
    assert config.webhooks.endpoints == []


def test_server_config_load_webhooks_from_file(tmp_path: Path) -> None:
    """Webhook endpoints are parsed from the config file."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "config.yaml"

    data = {
        "webhooks": {
            "enabled": True,
            "endpoints": [
                {
                    "url": "https://n8n.homelab.local/webhook/supernote",
                    "user": "alice@example.com",
                    "secret": "hmac-secret-key",
                    "events": ["note.sync_completed"],
                }
            ],
        }
    }
    with open(config_file, "w") as f:
        yaml.safe_dump(data, f)

    config = ServerConfig.load(config_dir)

    assert config.webhooks.enabled is True
    assert len(config.webhooks.endpoints) == 1
    endpoint = config.webhooks.endpoints[0]
    assert endpoint.url == "https://n8n.homelab.local/webhook/supernote"
    assert endpoint.user == "alice@example.com"
    assert endpoint.secret == "hmac-secret-key"
    assert endpoint.events == ["note.sync_completed"]


def test_server_config_webhooks_enabled_env_var_override(tmp_path: Path) -> None:
    """SUPERNOTE_WEBHOOKS_ENABLED overrides the config file value."""
    config_dir = tmp_path / "config"
    with patch.dict(os.environ, {"SUPERNOTE_WEBHOOKS_ENABLED": "true"}):
        config = ServerConfig.load(config_dir)
        assert config.webhooks.enabled is True


@pytest.mark.parametrize(
    "invalid_url",
    [
        "",
        "ftp://example.com/webhook",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http:///missing-host",
        "not-a-url",
    ],
)
def test_webhook_endpoint_config_rejects_invalid_urls(invalid_url: str) -> None:
    """WebhookEndpointConfig only accepts http and https URLs with a valid host."""
    with pytest.raises(ValueError, match="http or https scheme"):
        WebhookEndpointConfig(url=invalid_url, user="alice@example.com")


@pytest.mark.parametrize("invalid_user", ["", "   "])
def test_webhook_endpoint_config_rejects_empty_user(invalid_user: str) -> None:
    """WebhookEndpointConfig requires a non-empty user email address."""
    with pytest.raises(ValueError, match="non-empty user email"):
        WebhookEndpointConfig(url="https://example.com/webhook", user=invalid_user)


def test_server_config_proxy_env_vars(tmp_path: Path) -> None:
    """Test that proxy configuration can be set via environment variables."""
    config_dir = tmp_path / "config"
    with patch.dict(
        os.environ,
        {
            "SUPERNOTE_PROXY_MODE": "strict",
            "SUPERNOTE_TRUSTED_PROXIES": "10.0.0.1,10.0.0.2",
        },
    ):
        config = ServerConfig.load(config_dir)
        assert config.proxy_mode == "strict"
        # The list should be parsed from the comma-separated string
        assert config.trusted_proxies == ["10.0.0.1", "10.0.0.2"]


def test_server_config_web_flags(tmp_path: Path) -> None:
    """Verify web_enabled and web_notebook_preview configuration loading."""
    config = ServerConfig()
    assert config.web_enabled is True
    assert config.web_notebook_preview is True
    assert config.mcp_enabled is True

    config_dir = tmp_path / "config"
    with patch.dict(
        os.environ,
        {
            "SUPERNOTE_WEB_ENABLED": "false",
            "SUPERNOTE_WEB_NOTEBOOK_PREVIEW": "0",
            "SUPERNOTE_MCP_ENABLED": "false",
        },
    ):
        loaded = ServerConfig.load(config_dir)
        assert loaded.web_enabled is False
        assert loaded.web_notebook_preview is False
        assert loaded.mcp_enabled is False


def test_server_config_ai_default_unconfigured() -> None:
    """AI providers and models are unconfigured by default."""
    config = ServerConfig()
    assert config.ai == AiConfig()
    assert config.ai.providers == {}
    assert config.ai.ocr is None
    assert config.ai.summary is None
    assert config.ai.embedding is None


def test_server_config_load_ai_from_file(tmp_path: Path) -> None:
    """Structured ai configuration is parsed from config.yaml."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "config.yaml"

    data = {
        "ai": {
            "providers": {
                "gemini": {"api_key": "gemini-key"},
                "openai": {
                    "base_url": "http://localhost:11434/v1",
                    "api_key": "ollama",
                },
            },
            "ocr": {
                "provider": "openai",
                "model": "qwen2.5-vl:7b",
                "max_concurrency": 2,
            },
            "summary": {
                "provider": "gemini",
                "model": "gemini-3.6-flash",
                "max_concurrency": 4,
            },
            "embedding": {
                "provider": "gemini",
                "model": "gemini-embedding-001",
                "max_concurrency": 8,
            },
        }
    }
    with open(config_file, "w") as f:
        yaml.safe_dump(data, f)

    config = ServerConfig.load(config_dir)

    assert config.ai.providers == {
        "gemini": ProviderConfig(api_key="gemini-key"),
        "openai": ProviderConfig(
            api_key="ollama",
            base_url="http://localhost:11434/v1",
        ),
    }
    assert config.ai.ocr == ModelConfig(
        provider="openai",
        model="qwen2.5-vl:7b",
        max_concurrency=2,
    )
    assert config.ai.summary == ModelConfig(
        provider="gemini",
        model="gemini-3.6-flash",
        max_concurrency=4,
    )
    assert config.ai.embedding == ModelConfig(
        provider="gemini",
        model="gemini-embedding-001",
        max_concurrency=8,
    )


def test_server_config_load_partial_ai_keeps_omitted_capabilities_none(
    tmp_path: Path,
) -> None:
    """Omitting ai.summary or ai.embedding in config.yaml leaves them disabled (None)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "config.yaml"

    data = {
        "ai": {
            "providers": {
                "gemini": {"api_key": "gemini-key"},
            },
            "ocr": {
                "provider": "gemini",
                "model": "gemini-3.6-flash",
            },
        }
    }
    with open(config_file, "w") as f:
        yaml.safe_dump(data, f)

    config = ServerConfig.load(config_dir)
    assert config.ai.ocr == ModelConfig(provider="gemini", model="gemini-3.6-flash")
    assert config.ai.summary is None
    assert config.ai.embedding is None


def test_server_config_legacy_gemini_syncs_to_ai(tmp_path: Path) -> None:
    """Legacy gemini_* fields and env vars populate config.ai automatically."""
    direct = ServerConfig(
        gemini_api_key="legacy-key",
        gemini_ocr_model="gemini-custom-ocr",
        gemini_embedding_model="gemini-custom-embed",
        gemini_max_concurrency=3,
    )
    assert direct.ai.providers["gemini"] == ProviderConfig(api_key="legacy-key")
    assert direct.ai.ocr == ModelConfig(
        provider="gemini",
        model="gemini-custom-ocr",
        max_concurrency=3,
    )
    assert direct.ai.summary == ModelConfig(
        provider="gemini",
        model="gemini-custom-ocr",
        max_concurrency=3,
    )
    assert direct.ai.embedding == ModelConfig(
        provider="gemini",
        model="gemini-custom-embed",
        max_concurrency=3,
    )

    config_dir = tmp_path / "config"
    with patch.dict(
        os.environ,
        {
            "SUPERNOTE_GEMINI_API_KEY": "env-gemini-key",
            "SUPERNOTE_GEMINI_OCR_MODEL": "gemini-env-ocr",
            "SUPERNOTE_GEMINI_EMBEDDING_MODEL": "gemini-env-embed",
            "SUPERNOTE_GEMINI_MAX_CONCURRENCY": "7",
        },
    ):
        loaded = ServerConfig.load(config_dir)
        assert loaded.ai.providers["gemini"] == ProviderConfig(api_key="env-gemini-key")
        assert loaded.ai.ocr == ModelConfig(
            provider="gemini",
            model="gemini-env-ocr",
            max_concurrency=7,
        )
        assert loaded.ai.summary == ModelConfig(
            provider="gemini",
            model="gemini-env-ocr",
            max_concurrency=7,
        )
        assert loaded.ai.embedding == ModelConfig(
            provider="gemini",
            model="gemini-env-embed",
            max_concurrency=7,
        )


def test_model_config_validation() -> None:
    """ModelConfig validates non-empty provider, model, and positive max_concurrency."""
    with pytest.raises(ValueError, match="non-empty provider"):
        ModelConfig(provider="  ", model="gemini-3.6-flash")

    with pytest.raises(ValueError, match="non-empty model"):
        ModelConfig(provider="gemini", model="")

    with pytest.raises(ValueError, match="max_concurrency must be >= 1"):
        ModelConfig(provider="gemini", model="gemini-3.6-flash", max_concurrency=0)


def test_server_config_trace_log_flags(tmp_path: Path) -> None:
    """Verify trace_log_file and trace_log_unsafe defaults and env overrides."""
    config = ServerConfig()
    assert config.trace_log_unsafe is False

    config_dir = tmp_path / "config"
    custom_trace = str(tmp_path / "custom_trace.log")
    with patch.dict(
        os.environ,
        {
            "SUPERNOTE_TRACE_LOG_FILE": custom_trace,
            "SUPERNOTE_TRACE_LOG_UNSAFE": "true",
        },
    ):
        loaded = ServerConfig.load(config_dir)
        assert loaded.trace_log_file == custom_trace
        assert loaded.trace_log_unsafe is True
