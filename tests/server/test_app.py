"""Tests for application-level functionality including proxy header handling.

These tests verify that the server correctly handles X-Forwarded-* headers
when deployed behind a reverse proxy, with different proxy modes.
"""

import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient
from pytest_aiohttp import AiohttpClient
from sqlalchemy import delete, select

from supernote.models.file_device import FileUploadApplyLocalDTO
from supernote.server.app import bootstrap_ephemeral_user, create_app
from supernote.server.config import ServerConfig
from supernote.server.db.models.user import UserDO
from supernote.server.services.processor_modules.png_conversion import (
    PngConversionModule,
)


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


async def test_static_frontend_sha256_fallback(client: TestClient) -> None:
    """Verify that index.html and client.js include fallback for SHA-256 in insecure contexts."""
    resp = await client.get("/")
    assert resp.status == 200
    assert resp.headers.get("Cache-Control") == "no-cache"
    html = await resp.text()
    assert "js-sha256" in html
    assert "socket.io" in html

    resp = await client.get("/static/js/api/client.js")
    assert resp.status == 200
    assert resp.headers.get("Cache-Control") == "no-cache"
    js = await resp.text()
    assert "crypto.subtle" in js
    assert "window.sha256" in js
    assert "connectSocket" in js
    assert "supernote:task-sync" in js
    assert "supernote:file-sync" in js
    assert "supernote:digest-sync" in js


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/static/js/main.js",
        "/static/style.css",
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
def test_png_module_registration_matrix(
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
    page_modules = app["processor_service"].page_modules
    has_png = any(isinstance(m, PngConversionModule) for m in page_modules)
    assert has_png is expected_png


async def test_bootstrap_ephemeral_user(client: TestClient) -> None:
    """Verify bootstrap_ephemeral_user registers debug@example.com as an admin with system folders."""
    assert client.app is not None
    session_manager = client.app["session_manager"]
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

    integrity_service = client.app["integrity_service"]
    report = await integrity_service.verify_user_storage(user.id)
    assert report.scanned == 8
    assert report.ok == 8


STATIC_DIR = Path(__file__).resolve().parents[2] / "supernote" / "server" / "static"


def test_use_toast_composable_exists() -> None:
    """Verify that the shared useToast composable exists and exports toast helpers."""
    toast_path = STATIC_DIR / "js" / "composables" / "useToast.js"
    assert toast_path.is_file(), "useToast.js composable must exist"
    content = toast_path.read_text(encoding="utf-8")
    assert "export function useToast" in content
    assert "export function showToast" in content
    assert "export function dismissToast" in content


def test_index_html_renders_toast_container() -> None:
    """Verify that index.html includes the non-blocking toast notification stack."""
    index_path = STATIC_DIR / "index.html"
    html = index_path.read_text(encoding="utf-8")
    assert 'v-for="toast in toasts"' in html
    assert "dismissToast(toast.id)" in html
    assert "toast.message" in html


def test_no_blocking_alert_calls_in_static_js() -> None:
    """Verify that no blocking window.alert() calls remain in static JS files."""
    js_dir = STATIC_DIR / "js"
    offending_files: list[str] = []
    for js_file in sorted(js_dir.rglob("*.js")):
        content = js_file.read_text(encoding="utf-8")
        if "alert(" in content:
            offending_files.append(str(js_file.relative_to(STATIC_DIR)))
    assert offending_files == [], (
        f"Found blocking alert() calls in: {', '.join(offending_files)}"
    )


async def test_toast_static_asset_served(client: TestClient) -> None:
    """Verify that /static/js/composables/useToast.js and index.html are served properly."""
    resp = await client.get("/static/js/composables/useToast.js")
    assert resp.status == 200
    js_text = await resp.text()
    assert "useToast" in js_text

    index_resp = await client.get("/")
    assert index_resp.status == 200
    html_text = await index_resp.text()
    assert "toast in toasts" in html_text
