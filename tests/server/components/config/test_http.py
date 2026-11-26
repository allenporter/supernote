"""Integration tests for the `config` component HTTP routes via `ConfigClient`."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.config import ConfigClient
from supernote.client.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
)
from supernote.client.extended import ExtendedClient
from supernote.models.config import (
    ComponentConfigSource,
    ComponentFieldSpecVO,
    ComponentFieldType,
    ComponentStatusVO,
    ServerFeaturesVO,
)
from supernote.server.components.config.service import CONFIG_SERVICE_KEY
from supernote.server.config import ServerConfig
from supernote.server.keys import COMPONENT_LOADER_KEY, CONFIG_KEY

WEBHOOK_FIELDS = [
    ComponentFieldSpecVO(
        name="enabled", type=ComponentFieldType.BOOLEAN, default=False
    ),
    ComponentFieldSpecVO(name="endpoints", type=ComponentFieldType.ARRAY, default=[]),
]


@pytest.fixture
def admin_config_client(
    config_client: ConfigClient, admin_user_id: int
) -> ConfigClient:
    """`ConfigClient` whose session user has been promoted to admin."""
    del admin_user_id
    return config_client


async def test_get_features_as_non_admin(
    client: TestClient,
    config_client: ConfigClient,
) -> None:
    """Any signed-in user sees running component domains, tracking live reconfiguration."""
    loader = client.app[COMPONENT_LOADER_KEY]
    expected = sorted(
        comp.domain for comp in loader.components if loader.is_running(comp.domain)
    )
    assert await config_client.get_features() == ServerFeaturesVO(
        running_components=expected
    )
    assert "schedule" in expected
    assert "webhooks" not in expected
    assert "wiki" not in expected

    await client.app[CONFIG_SERVICE_KEY].update_component_config(
        "webhooks", {"enabled": True, "endpoints": []}
    )
    assert await config_client.get_features() == ServerFeaturesVO(
        running_components=sorted([*expected, "webhooks"])
    )


async def test_get_features_requires_auth(client: TestClient) -> None:
    """Unauthenticated requests are rejected by the auth middleware."""
    resp = await client.get("/api/extended/system/features")
    assert resp.status == 401


async def test_list_components_as_admin(admin_config_client: ConfigClient) -> None:
    """Admins see full effective config and field specs for all built-in components."""
    by_domain = {c.domain: c for c in await admin_config_client.list_components()}
    assert "wiki" in by_domain
    assert "config" in by_domain
    assert by_domain["webhooks"] == ComponentStatusVO(
        domain="webhooks",
        enabled=False,
        running=False,
        source=ComponentConfigSource.DEFAULT,
        read_only=False,
        runtime_configurable=True,
        restart_required=False,
        config={"enabled": False},
        fields=WEBHOOK_FIELDS,
    )


async def test_admin_endpoints_reject_non_admin(config_client: ConfigClient) -> None:
    """Non-admin interactive sessions receive 403 Forbidden on admin endpoints."""
    with pytest.raises(ForbiddenException):
        await config_client.list_components()
    with pytest.raises(ForbiddenException):
        await config_client.update_component("webhooks", {"enabled": True})


async def test_update_component_live_reconfigures(
    admin_config_client: ConfigClient,
) -> None:
    """Updating `webhooks` live-starts and stops the runtime-configurable component."""
    endpoints = [
        {
            "url": "http://127.0.0.1:9999/live-hook",
            "user": "admin@example.com",
            "secret": "top-secret-hmac",
            "events": ["*"],
        }
    ]
    enabled = await admin_config_client.update_component(
        "webhooks", {"enabled": True, "endpoints": endpoints}
    )
    redacted_endpoints = [{**endpoints[0], "secret": "***"}]
    assert enabled == ComponentStatusVO(
        domain="webhooks",
        enabled=True,
        running=True,
        source=ComponentConfigSource.DATABASE,
        read_only=False,
        runtime_configurable=True,
        restart_required=False,
        config={"enabled": True, "endpoints": redacted_endpoints},
        fields=WEBHOOK_FIELDS,
    )

    disabled = await admin_config_client.update_component(
        "webhooks", {"enabled": False, "endpoints": []}
    )
    assert disabled == ComponentStatusVO(
        domain="webhooks",
        enabled=False,
        running=False,
        source=ComponentConfigSource.DATABASE,
        read_only=False,
        runtime_configurable=True,
        restart_required=False,
        config={"enabled": False, "endpoints": []},
        fields=WEBHOOK_FIELDS,
    )


@pytest.mark.parametrize(
    ("domain", "config"),
    [
        ("nonexistent", {"enabled": True}),
        ("webhooks", {"enabled": "not-a-bool"}),
        ("webhooks", {"enabled": True, "unknown_field": 1}),
        ("wiki", {"enabled": True, "auto_compile": "not-a-bool"}),
    ],
)
async def test_update_component_rejects_invalid_payloads(
    admin_config_client: ConfigClient,
    domain: str,
    config: dict[str, Any],
) -> None:
    """Unknown domains, non-boolean flags, and unknown fields return 400 Bad Request."""
    with pytest.raises(BadRequestException):
        await admin_config_client.update_component(domain, config)


async def test_update_component_marks_restart_required(
    admin_config_client: ConfigClient,
) -> None:
    """Non-runtime-configurable components set `restart_required` when enabled differs from running."""
    assert await admin_config_client.update_component(
        "metrics", {"enabled": False}
    ) == ComponentStatusVO(
        domain="metrics",
        enabled=False,
        running=True,
        source=ComponentConfigSource.DATABASE,
        read_only=False,
        runtime_configurable=False,
        restart_required=True,
        config={"enabled": False, "path": "/metrics"},
        fields=[
            ComponentFieldSpecVO(
                name="enabled", type=ComponentFieldType.BOOLEAN, default=True
            ),
            ComponentFieldSpecVO(
                name="path", type=ComponentFieldType.STRING, default="/metrics"
            ),
        ],
    )


async def test_update_component_blocks_env_pinned(
    client: TestClient,
    admin_config_client: ConfigClient,
) -> None:
    """Updating a component pinned by environment variables returns 409 Conflict."""
    server_cfg: ServerConfig = client.app[CONFIG_KEY]
    with patch.dict(os.environ, {"SUPERNOTE_WEBHOOKS_ENABLED": "true"}):
        server_cfg._component_sources["webhooks"] = ComponentConfigSource.ENV
        try:
            with pytest.raises(ConflictException):
                await admin_config_client.update_component(
                    "webhooks", {"enabled": False}
                )
        finally:
            server_cfg._component_sources.pop("webhooks", None)


async def test_update_component_blocks_protected_and_dependent_components(
    admin_config_client: ConfigClient,
) -> None:
    """Disabling `web_ui` or disabling `conversion` while `summary` is enabled returns 409 Conflict."""
    with pytest.raises(ConflictException):
        await admin_config_client.update_component("web_ui", {"enabled": False})
    with pytest.raises(ConflictException):
        await admin_config_client.update_component("conversion", {"enabled": False})


async def test_admin_endpoints_reject_static_api_key(
    client: TestClient,
    admin_config_client: ConfigClient,
    extended_client: ExtendedClient,
) -> None:
    """Static API keys are blocked by @require_admin on component config endpoints."""
    del admin_config_client
    created = await extended_client.create_api_key("Component Test Key")
    api_key_headers = {"Authorization": f"Bearer {created.key}"}

    get_resp = await client.get(
        "/api/extended/system/components", headers=api_key_headers
    )
    assert get_resp.status == 403

    put_resp = await client.put(
        "/api/extended/system/components/webhooks",
        headers=api_key_headers,
        json={"config": {"enabled": True}},
    )
    assert put_resp.status == 403
