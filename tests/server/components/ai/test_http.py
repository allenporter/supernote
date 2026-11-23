"""Unit tests for `supernote.server.components.ai.http` (`GET /api/extended/ai/status`)."""

from __future__ import annotations

from aiohttp.test_utils import TestClient, TestServer

from supernote.server.components.ai import AiComponent
from supernote.server.components.fake_ai import FakeAiComponent
from supernote.server.components.http import HttpRegistrar
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig, ServerConfig
from supernote.server.core import ComponentLoader, ServerCore


async def _setup_ai_http(core: ServerCore) -> tuple[ComponentLoader, AiComponent]:
    loader = ComponentLoader()
    ai_component = AiComponent()
    loader.register(ai_component)
    loader.register(FakeAiComponent())

    await loader.async_setup_all(core, {})
    await loader.async_load_all_platforms(core)
    await loader.async_load_platform("http", core, HttpRegistrar())
    return loader, ai_component


async def test_ai_status_endpoint_reports_unconfigured_models(
    component_core: ServerCore,
) -> None:
    loader, _ = await _setup_ai_http(component_core)

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
    loader, ai_component = await _setup_ai_http(component_core)
    ai_component.get_platform_registrar().apply_to_app(
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
