"""Tests for application-level functionality including proxy header handling.

These tests verify that the server correctly handles X-Forwarded-* headers
when deployed behind a reverse proxy, with different proxy modes.
"""

import argparse
import dataclasses
import logging
import subprocess
import sys
from typing import Any

import pytest
from aiohttp.test_utils import TestClient
from pytest_aiohttp import AiohttpClient
from sqlalchemy import delete, select

from supernote.models.file_device import FileUploadApplyLocalDTO
from supernote.server.app import (
    bootstrap_ephemeral_user,
    create_app,
    run,
)
from supernote.server.components.fake_ai import FakeAiComponent
from supernote.server.components.search import SEARCH_SERVICE_KEY
from supernote.server.components.webhooks import WebhooksComponent
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig, ServerConfig
from supernote.server.core import ComponentLoader, ServerCore
from supernote.server.db.models.user import UserDO
from supernote.server.keys import (
    COMPONENT_LOADER_KEY,
    CORE_KEY,
    EMBEDDING_MODEL_KEY,
    INTEGRITY_SERVICE_KEY,
    OCR_MODEL_KEY,
    PROCESSOR_SERVICE_KEY,
    SESSION_MANAGER_KEY,
    USER_SERVICE_KEY,
)
from supernote.server.services.processor_modules.png_conversion import (
    PngConversionModule,
)
from supernote.server.trace import ACCESS_LOG_FORMAT, SanitizedAccessLogger


def test_import_does_not_load_google_genai() -> None:
    """Importing the server bootstrap module should not eagerly import
    `google-genai` (see issue #106).

    `google-genai` is only needed once a Gemini API key is configured. Run
    in a subprocess so the check isn't polluted by other tests in this
    session having already imported the module.
    """
    check = (
        "import sys; import supernote.server.app; "
        "loaded = sorted("
        "m for m in sys.modules "
        "if m == 'google.genai' or m.startswith('google.genai.')"
        "); "
        "print(','.join(loaded))"
    )
    result = subprocess.run(
        [sys.executable, "-c", check],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "", (
        f"google-genai modules unexpectedly loaded: {result.stdout.strip()}"
    )


# Test for default proxy mode (disabled)
async def test_proxy_headers_ignored_by_default(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Verify that proxy headers are ignored when proxy_mode is None (default)."""

    payload = FileUploadApplyLocalDTO(
        equipment_no="TEST_DEVICE",
        file_name="test_default.note",
        path="/",
        size="1234",
    ).to_dict()

    # Send proxy headers (should be ignored)
    proxy_headers = {
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "malicious-domain.com",
        **auth_headers,
    }

    resp = await client.post(
        "/api/file/3/files/upload/apply", json=payload, headers=proxy_headers
    )
    assert resp.status == 200
    data = await resp.json()

    full_upload_url = data.get("fullUploadUrl")
    assert full_upload_url is not None

    # Should NOT use forwarded headers, should use actual test client host
    assert not full_upload_url.startswith("https://malicious-domain.com"), (
        f"Proxy headers should be ignored by default, got: {full_upload_url}"
    )
    # Should use the test server's actual scheme and host
    assert (
        "http://127.0.0.1" in full_upload_url or "http://localhost" in full_upload_url
    )


@pytest.mark.parametrize("proxy_mode", ["relaxed"])
async def test_upload_url_proxy_headers_relaxed(
    client: TestClient, auth_headers: dict[str, str], proxy_mode: str
) -> None:
    """Verify that upload URLs respect X-Forwarded headers in relaxed mode."""

    # Payload for upload apply
    payload = FileUploadApplyLocalDTO(
        equipment_no="TEST_DEVICE",
        file_name="test_proxy.note",
        path="/",
        size="1234",
    ).to_dict()

    # Headers mocking a proxy
    proxy_headers = {
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "my-public-domain.com",
        **auth_headers,
    }

    resp = await client.post(
        "/api/file/3/files/upload/apply", json=payload, headers=proxy_headers
    )
    assert resp.status == 200
    data = await resp.json()

    full_upload_url = data.get("fullUploadUrl")
    assert full_upload_url is not None

    # Verification: Should use forwarded headers
    assert full_upload_url.startswith("https://my-public-domain.com"), (
        f"Got URL: {full_upload_url}"
    )


@pytest.mark.parametrize("proxy_mode", ["relaxed"])
async def test_upload_url_no_proxy_headers(
    client: TestClient, auth_headers: dict[str, str], proxy_mode: str
) -> None:
    """Verify that upload URLs work without proxy headers."""

    payload = FileUploadApplyLocalDTO(
        equipment_no="TEST_DEVICE",
        file_name="test_no_proxy.note",
        path="/",
        size="1234",
    ).to_dict()

    resp = await client.post(
        "/api/file/3/files/upload/apply", json=payload, headers=auth_headers
    )
    assert resp.status == 200
    data = await resp.json()

    full_upload_url = data.get("fullUploadUrl")
    assert full_upload_url is not None

    # Should use the test client's host (127.0.0.1 or similar)
    assert "http://127.0.0.1:" in full_upload_url


@pytest.mark.parametrize("proxy_mode", ["relaxed"])
async def test_upload_url_with_port_in_forwarded_host(
    client: TestClient, auth_headers: dict[str, str], proxy_mode: str
) -> None:
    """Verify that upload URLs respect X-Forwarded-Host with port."""

    payload = FileUploadApplyLocalDTO(
        equipment_no="TEST_DEVICE",
        file_name="test_port.note",
        path="/",
        size="1234",
    ).to_dict()

    # Headers with port in host
    proxy_headers = {
        "X-Forwarded-Proto": "http",
        "X-Forwarded-Host": "localhost:9888",
        **auth_headers,
    }

    resp = await client.post(
        "/api/file/3/files/upload/apply", json=payload, headers=proxy_headers
    )
    assert resp.status == 200
    data = await resp.json()

    full_upload_url = data.get("fullUploadUrl")
    assert full_upload_url is not None

    # Should use forwarded host with port
    assert full_upload_url.startswith("http://localhost:9888"), (
        f"Got URL: {full_upload_url}"
    )


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/static/style.css",
        "/static/js/main.js",
        "/static/js/api/client.js",
        "/static/js/composables/useToast.js",
    ],
)
async def test_static_frontend_cache_control_no_cache(
    client: TestClient, path: str
) -> None:
    """Verify that index.html and /static/ assets set Cache-Control: no-cache."""
    resp = await client.get(path)
    assert resp.status == 200
    assert resp.headers.get("Cache-Control") == "no-cache"


async def test_static_frontend_disabled_when_web_enabled_false(
    aiohttp_client: AiohttpClient,
    server_config: ServerConfig,
) -> None:
    """Verify that index and static routes are not registered when web_enabled is False."""
    disabled_config = dataclasses.replace(server_config, web_enabled=False)
    app = create_app(disabled_config)
    client = await aiohttp_client(app)

    resp = await client.get("/")
    assert resp.status == 404

    resp = await client.get("/static/js/api/client.js")
    assert resp.status == 404


@pytest.mark.parametrize(
    ("web_enabled", "web_notebook_preview", "gemini_api_key", "expected_png"),
    [
        (False, False, "fake-key", True),
        (True, True, None, True),
        (True, False, None, False),
        (False, True, None, False),
    ],
)
async def test_png_module_registration_matrix(
    aiohttp_client: AiohttpClient,
    server_config: ServerConfig,
    web_enabled: bool,
    web_notebook_preview: bool,
    gemini_api_key: str | None,
    expected_png: bool,
) -> None:
    """Verify PngConversionModule is only registered when OCR or web notebook preview is active."""
    cfg = dataclasses.replace(
        server_config,
        web_enabled=web_enabled,
        web_notebook_preview=web_notebook_preview,
        gemini_api_key=gemini_api_key,
    )
    app = create_app(cfg)
    await aiohttp_client(app)
    page_modules = app[PROCESSOR_SERVICE_KEY].page_modules
    has_png = any(isinstance(m, PngConversionModule) for m in page_modules)
    assert has_png is expected_png


async def test_bootstrap_ephemeral_user(client: TestClient) -> None:
    """Verify bootstrap_ephemeral_user registers debug@example.com as an admin with system folders."""
    assert client.app is not None
    session_manager = client.app[SESSION_MANAGER_KEY]
    async with session_manager.session() as session:
        await session.execute(delete(UserDO))
        await session.commit()

    await bootstrap_ephemeral_user(client.app)

    async with session_manager.session() as session:
        user = (
            await session.execute(
                select(UserDO).where(UserDO.email == "debug@example.com")
            )
        ).scalar_one()
        assert user.is_admin is True

    integrity_service = client.app[INTEGRITY_SERVICE_KEY]
    report = await integrity_service.verify_user_storage(user.id)
    assert report.scanned == 8
    assert report.ok == 8


def test_run_configures_default_info_level_and_sanitized_access_logger(
    monkeypatch: pytest.MonkeyPatch,
    server_config: ServerConfig,
) -> None:
    """Verify run() defaults root logging to INFO and wires SanitizedAccessLogger into web.run_app."""
    monkeypatch.delenv("SUPERNOTE_LOG_LEVEL", raising=False)
    cfg = dataclasses.replace(server_config, log_level="INFO")
    monkeypatch.setattr(ServerConfig, "load", lambda _dir=None: cfg)

    captured_kwargs: dict[str, Any] = {}

    def fake_run_app(app: Any, **kwargs: Any) -> None:
        captured_kwargs["app"] = app
        captured_kwargs.update(kwargs)

    monkeypatch.setattr("supernote.server.app.web.run_app", fake_run_app)

    run(argparse.Namespace(config_dir=None))

    assert logging.getLogger().level == logging.INFO
    assert logging.getLogger("aiosqlite").level == logging.INFO
    assert logging.getLogger("asyncio").level == logging.INFO
    assert captured_kwargs["access_log_class"] is SanitizedAccessLogger
    assert captured_kwargs["access_log_format"] == ACCESS_LOG_FORMAT


def test_run_respects_config_and_env_log_level(
    monkeypatch: pytest.MonkeyPatch,
    server_config: ServerConfig,
) -> None:
    """Verify run() applies config.log_level while keeping noisy library loggers at INFO+."""
    monkeypatch.setattr("supernote.server.app.web.run_app", lambda *_a, **_kw: None)

    try:
        monkeypatch.delenv("SUPERNOTE_LOG_LEVEL", raising=False)
        debug_cfg = dataclasses.replace(server_config, log_level="DEBUG")
        monkeypatch.setattr(ServerConfig, "load", lambda _dir=None: debug_cfg)

        run(argparse.Namespace(config_dir=None))
        assert logging.getLogger().level == logging.DEBUG
        assert logging.getLogger("aiosqlite").level == logging.INFO
        assert logging.getLogger("asyncio").level == logging.INFO

        monkeypatch.setenv("SUPERNOTE_LOG_LEVEL", "WARNING")
        warn_cfg = dataclasses.replace(server_config, log_level="WARNING")
        monkeypatch.setattr(ServerConfig, "load", lambda _dir=None: warn_cfg)

        run(argparse.Namespace(config_dir=None))
        assert logging.getLogger().level == logging.WARNING
        assert logging.getLogger("aiosqlite").level == logging.WARNING
        assert logging.getLogger("asyncio").level == logging.WARNING
    finally:
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger("aiosqlite").setLevel(logging.INFO)
        logging.getLogger("asyncio").setLevel(logging.INFO)


async def test_jwt_auth_middleware_blocks_api_key_on_interactive_route(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify jwt_auth_middleware rejects static API keys on @interactive_session_only handlers."""
    create_resp = await client.post(
        "/api/extended/keys",
        json={"name": "Middleware Check"},
        headers=auth_headers,
    )
    assert create_resp.status == 200
    raw_key = (await create_resp.json())["key"]
    api_key_headers = {"Authorization": f"Bearer {raw_key}"}

    # Standard API route succeeds with Bearer API key
    ok_resp = await client.post(
        "/api/file/capacity/query", json={}, headers=api_key_headers
    )
    assert ok_resp.status == 200

    # @interactive_session_only route returns 403 before reaching the handler
    forbidden_resp = await client.get("/api/extended/keys", headers=api_key_headers)
    assert forbidden_resp.status == 403
    assert "Interactive session required" in (await forbidden_resp.json())["errorMsg"]


async def test_jwt_auth_middleware_accepts_oauth_token_on_file_apis_and_blocks_interactive_route(
    client: TestClient,
    create_test_user: None,
) -> None:
    """Verify OAuth 2.1 Bearer tokens authenticate file/extended APIs and are blocked on @interactive_session_only routes."""
    user_service = client.app[USER_SERVICE_KEY]
    user_id = await user_service.get_user_id("test@example.com")

    oauth_token, _ = await user_service.create_oauth_grant(
        user_id, "composer_app", ["supernote:all"]
    )
    oauth_headers = {"Authorization": f"Bearer {oauth_token}"}

    # File and extended REST endpoints succeed with OAuth 2.1 Bearer token
    list_resp = await client.post(
        "/api/file/list/query",
        json={"directoryId": 0, "pageNo": 1, "pageSize": 20},
        headers=oauth_headers,
    )
    assert list_resp.status == 200
    assert (await list_resp.json())["success"] is True

    events_resp = await client.get("/api/extended/events", headers=oauth_headers)
    assert events_resp.status == 200

    # @interactive_session_only routes remain forbidden (403)
    forbidden_resp = await client.get("/api/extended/keys", headers=oauth_headers)
    assert forbidden_resp.status == 403
    assert "Interactive session required" in (await forbidden_resp.json())["errorMsg"]


async def test_create_app_wires_server_core_and_skips_disabled_webhooks(
    aiohttp_client: AiohttpClient,
    server_config: ServerConfig,
) -> None:
    """Verify `create_app` exposes `ServerCore` + `ComponentLoader` and omits disabled webhooks."""
    config = dataclasses.replace(server_config, web_enabled=False)
    app = create_app(config)

    assert isinstance(app[CORE_KEY], ServerCore)
    assert isinstance(app[COMPONENT_LOADER_KEY], ComponentLoader)
    assert app[COMPONENT_LOADER_KEY].get("webhooks") is None

    test_client = await aiohttp_client(app)
    resp = await test_client.get("/api/health")
    assert resp.status == 200


async def test_create_app_registers_and_runs_webhooks_component_when_enabled(
    aiohttp_client: AiohttpClient,
    server_config: ServerConfig,
    session_manager: Any,
) -> None:
    """Verify enabled webhooks are registered and started via `ComponentLoader`."""
    config = dataclasses.replace(
        server_config,
        web_enabled=False,
        webhooks={
            "enabled": True,
            "endpoints": [
                {
                    "url": "http://127.0.0.1:9999/hook",
                    "user": "test@example.com",
                    "secret": "secret",
                }
            ],
        },
    )
    app = create_app(config)

    comp = app[COMPONENT_LOADER_KEY].get("webhooks")
    assert isinstance(comp, WebhooksComponent)

    test_client = await aiohttp_client(app)
    resp = await test_client.get("/api/health")
    assert resp.status == 200


async def test_create_app_loads_fake_ai_only_when_configured(
    aiohttp_client: AiohttpClient,
    server_config: ServerConfig,
) -> None:
    """Verify `create_app` registers `fake_ai` only when configured and resolves models via `AiRegistrar` on startup."""
    default_app = create_app(dataclasses.replace(server_config, web_enabled=False))
    assert default_app[COMPONENT_LOADER_KEY].get("fake_ai") is None

    fake_config = dataclasses.replace(
        server_config,
        web_enabled=False,
        ai=AiConfig(
            providers={"local_fake": ProviderConfig(type="Fake")},
            ocr=ModelConfig(provider="local_fake", model="fake-ocr"),
            embedding=ModelConfig(provider="local_fake", model="fake-embed"),
        ),
    )
    fake_app = create_app(fake_config)
    assert isinstance(fake_app[COMPONENT_LOADER_KEY].get("fake_ai"), FakeAiComponent)

    await aiohttp_client(fake_app)
    ocr_model = fake_app[OCR_MODEL_KEY]
    assert ocr_model is not None
    assert ocr_model.model_id == "fake-ocr"
    assert fake_app[EMBEDDING_MODEL_KEY] is not None
    assert fake_app[SEARCH_SERVICE_KEY].embedding_model is fake_app[EMBEDDING_MODEL_KEY]
