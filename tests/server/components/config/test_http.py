"""Integration tests for `GET` and `PUT /api/extended/system/components` HTTP routes."""

from __future__ import annotations

import hashlib
import os
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient
from sqlalchemy import delete

from supernote.models.user import UserRegisterDTO
from supernote.server.config import ComponentConfigSource, ServerConfig
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.keys import CONFIG_KEY
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.user import UserService


@pytest.fixture
async def setup_users(
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
) -> tuple[str, str]:
    """Create an admin user and a regular user and return their session tokens."""
    async with session_manager.session() as session:
        await session.execute(delete(UserDO))
        await session.commit()

    service = UserService(server_config.auth, coordination_service, session_manager)
    pw_md5 = hashlib.md5(b"pw").hexdigest()
    await service.register(
        UserRegisterDTO(email="admin@example.com", password=pw_md5, user_name="Admin")
    )
    await service.register(
        UserRegisterDTO(email="user@example.com", password=pw_md5, user_name="User")
    )
    admin_token = await service.create_session("admin@example.com")
    user_token = await service.create_session("user@example.com")
    return admin_token, user_token


@pytest.fixture
def admin_headers(setup_users: tuple[str, str]) -> dict[str, str]:
    """Interactive session headers for an admin user."""
    admin_token, _ = setup_users
    return {"x-access-token": admin_token}


@pytest.fixture
def user_headers(setup_users: tuple[str, str]) -> dict[str, str]:
    """Interactive session headers for a non-admin user."""
    _, user_token = setup_users
    return {"x-access-token": user_token}


async def test_list_system_components_as_admin(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    """Admins see full effective config and field specs for all built-in components."""
    resp = await client.get("/api/extended/system/components", headers=admin_headers)
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True

    by_domain = {c["domain"]: c for c in data["components"]}
    assert "webhooks" in by_domain
    assert "wiki" in by_domain
    assert "config" in by_domain
    assert by_domain["webhooks"] == {
        "domain": "webhooks",
        "enabled": False,
        "running": False,
        "source": "default",
        "readOnly": False,
        "runtimeConfigurable": True,
        "restartRequired": False,
        "config": {"enabled": False},
        "fields": [
            {"name": "enabled", "type": "boolean", "default": False},
            {"name": "endpoints", "type": "array", "default": []},
        ],
    }


async def test_list_system_components_rejects_non_admin(
    client: TestClient,
    user_headers: dict[str, str],
) -> None:
    """Non-admin interactive sessions receive 403 Forbidden when listing components."""
    member_resp = await client.get(
        "/api/extended/system/components", headers=user_headers
    )
    assert member_resp.status == 403


async def test_update_system_component_live_reconfigures(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    """PUT /api/extended/system/components/webhooks live-starts and stops webhooks."""
    endpoints = [
        {
            "url": "http://127.0.0.1:9999/live-hook",
            "user": "admin@example.com",
            "secret": "top-secret-hmac",
            "events": ["*"],
        }
    ]
    put_resp = await client.put(
        "/api/extended/system/components/webhooks",
        headers=admin_headers,
        json={"config": {"enabled": True, "endpoints": endpoints}},
    )
    assert put_resp.status == 200
    assert (await put_resp.json())["component"] == {
        "domain": "webhooks",
        "enabled": True,
        "running": True,
        "source": "database",
        "readOnly": False,
        "runtimeConfigurable": True,
        "restartRequired": False,
        "config": {"enabled": True, "endpoints": endpoints},
        "fields": [
            {"name": "enabled", "type": "boolean", "default": False},
            {"name": "endpoints", "type": "array", "default": []},
        ],
    }

    disable_resp = await client.put(
        "/api/extended/system/components/webhooks",
        headers=admin_headers,
        json={"config": {"enabled": False, "endpoints": []}},
    )
    assert disable_resp.status == 200
    assert (await disable_resp.json())["component"] == {
        "domain": "webhooks",
        "enabled": False,
        "running": False,
        "source": "database",
        "readOnly": False,
        "runtimeConfigurable": True,
        "restartRequired": False,
        "config": {"enabled": False, "endpoints": []},
        "fields": [
            {"name": "enabled", "type": "boolean", "default": False},
            {"name": "endpoints", "type": "array", "default": []},
        ],
    }


async def test_update_system_component_rejects_non_admin(
    client: TestClient,
    user_headers: dict[str, str],
) -> None:
    """Non-admin interactive sessions receive 403 Forbidden on component updates."""
    forbidden = await client.put(
        "/api/extended/system/components/webhooks",
        headers=user_headers,
        json={"config": {"enabled": True}},
    )
    assert forbidden.status == 403


@pytest.mark.parametrize(
    ("domain", "payload"),
    [
        ("nonexistent", {"config": {"enabled": True}}),
        ("webhooks", {"config": {"enabled": "not-a-bool"}}),
        ("webhooks", {"config": {"enabled": True, "unknown_field": 1}}),
        ("wiki", {"config": {"enabled": True, "auto_compile": "not-a-bool"}}),
    ],
)
async def test_update_system_component_rejects_invalid_payloads(
    client: TestClient,
    admin_headers: dict[str, str],
    domain: str,
    payload: dict[str, Any],
) -> None:
    """Unknown domains, non-boolean flags, and unknown fields return 400 Bad Request."""
    resp = await client.put(
        f"/api/extended/system/components/{domain}",
        headers=admin_headers,
        json=payload,
    )
    assert resp.status == 400


async def test_update_system_component_marks_restart_required(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    """Non-runtime-configurable components set `restartRequired=True` when enabled differs from running."""
    toggle_metrics = await client.put(
        "/api/extended/system/components/metrics",
        headers=admin_headers,
        json={"config": {"enabled": False}},
    )
    assert toggle_metrics.status == 200
    assert (await toggle_metrics.json())["component"] == {
        "domain": "metrics",
        "enabled": False,
        "running": True,
        "source": "database",
        "readOnly": False,
        "runtimeConfigurable": False,
        "restartRequired": True,
        "config": {"enabled": False},
        "fields": [{"name": "enabled", "type": "boolean", "default": True}],
    }


async def test_update_system_component_blocks_env_pinned(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    """Updating a component pinned by environment variables returns 409 Conflict."""
    assert client.app is not None
    server_cfg: ServerConfig = client.app[CONFIG_KEY]
    with patch.dict(os.environ, {"SUPERNOTE_WEBHOOKS_ENABLED": "true"}):
        server_cfg._component_sources["webhooks"] = ComponentConfigSource.ENV
        try:
            conflict_resp = await client.put(
                "/api/extended/system/components/webhooks",
                headers=admin_headers,
                json={"config": {"enabled": False}},
            )
            assert conflict_resp.status == 409
        finally:
            server_cfg._component_sources.pop("webhooks", None)


async def test_update_system_component_blocks_protected_and_dependent_components(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    """Disabling `web_ui` or disabling `conversion` while `summary` is enabled returns 409 Conflict."""
    web_ui_resp = await client.put(
        "/api/extended/system/components/web_ui",
        headers=admin_headers,
        json={"config": {"enabled": False}},
    )
    assert web_ui_resp.status == 409

    conversion_resp = await client.put(
        "/api/extended/system/components/conversion",
        headers=admin_headers,
        json={"config": {"enabled": False}},
    )
    assert conversion_resp.status == 409


async def test_update_system_component_rejects_static_api_key(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    """Static API keys are blocked by @require_admin on component config endpoints."""
    key_resp = await client.post(
        "/api/extended/keys",
        json={"name": "Component Test Key"},
        headers=admin_headers,
    )
    assert key_resp.status == 200
    raw_key: Any = (await key_resp.json())["key"]
    api_key_headers = {"Authorization": f"Bearer {raw_key}"}

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
