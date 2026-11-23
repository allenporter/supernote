"""HTTP platform tests for `supernote.server.components.ai.http` (`GET /api/extended/ai/status`)."""

from __future__ import annotations

from pytest_aiohttp import AiohttpClient

from supernote.server.config import AiConfig, ModelConfig, ProviderConfig
from supernote.server.core import ServerCore
from tests.server.components.conftest import LoadComponents


async def test_ai_status_endpoint_requires_auth_and_reports_unconfigured_models(
    component_core: ServerCore,
    load_components: LoadComponents,
    aiohttp_client: AiohttpClient,
    auth_headers: dict[str, str],
) -> None:
    await load_components("http", "ai", "fake_ai")
    client = await aiohttp_client(component_core.app)

    unauth = await client.get("/api/extended/ai/status")
    assert unauth.status == 401

    resp = await client.get("/api/extended/ai/status", headers=auth_headers)
    assert resp.status == 200
    assert await resp.json() == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "hasApiKey": False,
        "ocrEnabled": False,
        "ocrModel": None,
        "summaryEnabled": False,
        "summaryModel": None,
        "vectorSearchEnabled": False,
        "embeddingModel": None,
        "model": None,
    }


async def test_ai_status_endpoint_reports_configured_models(
    component_core: ServerCore,
    load_components: LoadComponents,
    aiohttp_client: AiohttpClient,
    auth_headers: dict[str, str],
) -> None:
    component_core.config.ai = AiConfig(
        providers={"fake": ProviderConfig()},
        ocr=ModelConfig(provider="fake", model="fake-ocr"),
        summary=ModelConfig(provider="fake", model="fake-summary"),
        embedding=ModelConfig(provider="fake", model="fake-embed"),
    )

    await load_components("http", "ai", "fake_ai")
    client = await aiohttp_client(component_core.app)

    resp = await client.get("/api/extended/ai/status", headers=auth_headers)
    assert resp.status == 200
    assert await resp.json() == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "hasApiKey": True,
        "ocrEnabled": True,
        "ocrModel": "fake-ocr",
        "summaryEnabled": True,
        "summaryModel": "fake-summary",
        "vectorSearchEnabled": True,
        "embeddingModel": "fake-embed",
        "model": "fake-ocr",
    }
