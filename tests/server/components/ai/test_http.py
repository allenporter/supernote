"""Unit tests for `supernote.server.components.ai.http` (`GET /api/extended/ai/status`)."""

from __future__ import annotations

from aiohttp.test_utils import TestClient, TestServer

from supernote.server.components.ai import AI_REGISTRAR_KEY, AiComponent
from supernote.server.components.fake_ai import FakeAiComponent
from supernote.server.components.http import HTTP_REGISTRAR_KEY, HttpComponent
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig, ServerConfig
from supernote.server.core import ComponentLoader, ServerCore


async def _setup_ai_http(core: ServerCore) -> ComponentLoader:
    loader = ComponentLoader()
    loader.register(HttpComponent())
    loader.register(AiComponent())
    loader.register(FakeAiComponent())

    await loader.async_setup_all(core, {})
    ai_registrar = core.app[AI_REGISTRAR_KEY]
    for platform in ai_registrar.platforms:
        await loader.async_load_platform(platform, core, ai_registrar)
    http_registrar = core.app[HTTP_REGISTRAR_KEY]
    await loader.async_load_platform("http", core, http_registrar)
    return loader


async def test_ai_status_endpoint_reports_unconfigured_models(
    component_core: ServerCore,
) -> None:
    loader = await _setup_ai_http(component_core)

    async with TestClient(TestServer(component_core.app)) as client:
        resp = await client.get("/api/extended/ai/status")
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

    await loader.async_stop_all(component_core)


async def test_ai_status_endpoint_reports_configured_models(
    component_core: ServerCore,
) -> None:
    loader = await _setup_ai_http(component_core)
    component_core.app[AI_REGISTRAR_KEY].apply_to_app(
        component_core.app,
        ServerConfig(
            ai=AiConfig(
                providers={"fake": ProviderConfig()},
                ocr=ModelConfig(provider="fake", model="fake-ocr"),
                summary=ModelConfig(provider="fake", model="fake-summary"),
                embedding=ModelConfig(provider="fake", model="fake-embed"),
            )
        ),
    )

    async with TestClient(TestServer(component_core.app)) as client:
        resp = await client.get("/api/extended/ai/status")
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

    await loader.async_stop_all(component_core)
