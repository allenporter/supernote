"""Unit tests for `supernote.server.components.openai` (`OpenAIComponent`)."""

from __future__ import annotations

from typing import Any

from aiohttp import web

from supernote.server.ai.models.embedding import (
    ConcurrencyLimitedEmbeddingModel,
    EmbeddingTaskType,
)
from supernote.server.ai.models.summary import ConcurrencyLimitedSummaryModel
from supernote.server.components.ai import (
    EMBEDDING_MODEL_KEY,
    SUMMARY_MODEL_KEY,
    AiComponent,
)
from supernote.server.components.openai import OpenAIComponent
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig
from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_openai_component_registers_all_ai_platforms(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    loader = await load_components(
        "openai",
        configs={
            "openai": {
                "enabled": True,
                "base_url": "http://localhost:11434/v1",
                "api_key": "sk-local",
            }
        },
    )
    component = loader.get("openai")
    assert isinstance(component, OpenAIComponent)
    assert isinstance(component, Component)
    assert component.domain == "openai"
    assert component.dependencies == ("ai",)
    assert component.platforms == ("ocr", "summary", "embedding", "text")
    assert component._config.base_url == "http://localhost:11434/v1"
    assert component._config.providers["openai"].base_url == "http://localhost:11434/v1"

    ai_component = loader.get("ai")
    assert isinstance(ai_component, AiComponent)
    ai_registrar = ai_component.get_platform_registrar()

    assert ai_registrar.ocr_providers == ("openai",)
    assert ai_registrar.summary_providers == ("openai",)
    assert ai_registrar.embedding_providers == ("openai",)
    assert ai_registrar.text_providers == ("openai",)

    await loader.async_stop_all(component_core)


async def test_openai_component_routes_named_providers_to_distinct_servers(
    component_core: ServerCore,
    load_components: LoadComponents,
    aiohttp_server: Any,
) -> None:
    """Summary and embedding route HTTP requests to two distinct OpenAI-compatible servers."""
    ollama_hits: list[str] = []
    llamacpp_hits: list[str] = []

    async def handle_ollama_chat(request: web.Request) -> web.Response:
        body = await request.json()
        ollama_hits.append(body["model"])
        return web.json_response(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"segments":[{"date_range":"2026-11-09",'
                                '"summary":"ok","extracted_dates":["2026-11-09"],'
                                '"page_refs":[1]}]}'
                            )
                        }
                    }
                ]
            }
        )

    async def handle_llamacpp_embed(request: web.Request) -> web.Response:
        body = await request.json()
        llamacpp_hits.append(body["model"])
        return web.json_response({"data": [{"embedding": [0.3, 0.4, 0.5]}]})

    ollama_app = web.Application()
    ollama_app.router.add_post("/v1/chat/completions", handle_ollama_chat)
    ollama_srv = await aiohttp_server(ollama_app)

    llamacpp_app = web.Application()
    llamacpp_app.router.add_post("/v1/embeddings", handle_llamacpp_embed)
    llamacpp_srv = await aiohttp_server(llamacpp_app)

    component_core.config.ai = AiConfig(
        providers={
            "ollama": ProviderConfig(
                type="openai", base_url=str(ollama_srv.make_url("/v1"))
            ),
            "llamacpp": ProviderConfig(
                type="openai", base_url=str(llamacpp_srv.make_url("/v1"))
            ),
        },
        summary=ModelConfig(provider="ollama", model="gemma3:27b"),
        embedding=ModelConfig(provider="llamacpp", model="embeddinggemma"),
    )
    loader = await load_components("openai", start=False)

    model = component_core.app[SUMMARY_MODEL_KEY]
    assert isinstance(model, ConcurrencyLimitedSummaryModel)
    assert (model.provider, model.model_id) == ("ollama", "gemma3:27b")

    embedding = component_core.app[EMBEDDING_MODEL_KEY]
    assert isinstance(embedding, ConcurrencyLimitedEmbeddingModel)
    assert (embedding.provider, embedding.model_id) == ("llamacpp", "embeddinggemma")

    summary_res = await model.summarize("TRANSCRIPT:\nPage 1")
    assert summary_res.segments[0].summary == "ok"
    vec = await embedding.embed(
        "Page 1", task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT
    )
    assert vec == [0.3, 0.4, 0.5]
    assert ollama_hits == ["gemma3:27b"]
    assert llamacpp_hits == ["embeddinggemma"]

    await loader.async_stop_all(component_core)
