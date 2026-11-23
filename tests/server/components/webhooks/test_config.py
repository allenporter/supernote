"""Unit tests for `supernote.server.components.webhooks.config`."""

from __future__ import annotations

import pytest

from supernote.server.components.webhooks.config import (
    WebhookConfig,
    WebhookEndpointConfig,
)


def test_webhook_config_from_dict_parses_endpoints() -> None:
    config = WebhookConfig.from_dict(
        {
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
    )

    assert config.enabled is True
    assert len(config.endpoints) == 1
    endpoint = config.endpoints[0]
    assert endpoint.url == "https://n8n.homelab.local/webhook/supernote"
    assert endpoint.user == "alice@example.com"
    assert endpoint.secret == "hmac-secret-key"
    assert endpoint.events == ["note.sync_completed"]


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
