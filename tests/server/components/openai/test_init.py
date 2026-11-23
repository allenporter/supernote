"""Unit tests for `supernote.server.components.openai` (`OpenAIComponent`)."""

from __future__ import annotations

from typing import Any

from aiohttp import web

from supernote.server.ai.models.embedding import (
    ConcurrencyLimitedEmbeddingModel,
    EmbeddingTaskType,
)
from supernote.server.ai.models.summary import ConcurrencyLimitedSummaryModel
from supernote.server.components.ai import AiComponent
from supernote.server.components.openai import OpenAIComponent
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig, ServerConfig
from supernote.server.core import Component, ComponentLoader, ServerCore


async def test_openai_component_registers_all_ai_platforms(
    component_core: ServerCore,
) -> None:
    component = OpenAIComponent()
    assert isinstance(component, Component)
    assert component.domain == "openai"
    assert component.dependencies == ("ai",)
    assert component.platforms == ("ocr", "summary", "embedding")

    ai_component = AiComponent()
    loader = ComponentLoader()
    loader.register(ai_component)
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    await loader.async_load_all_platforms(component_core)
    ai_registrar = ai_component.get_platform_registrar()

    assert ai_registrar.ocr_providers == ("openai",)
    assert ai_registrar.summary_providers == ("openai",)
    assert ai_registrar.embedding_providers == ("openai",)

    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)


async def test_openai_component_routes_named_providers_to_distinct_servers(
    component_core: ServerCore,
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

    ai_component = AiComponent()
    loader = ComponentLoader()
    loader.register(ai_component)
    loader.register(OpenAIComponent())
    await loader.async_setup_all(component_core, {})
    await loader.async_load_all_platforms(component_core)
    ai_registrar = ai_component.get_platform_registrar()

    config = ServerConfig(
        ai=AiConfig(
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
    )
    model = ai_registrar.create_summary_model(config)
    assert isinstance(model, ConcurrencyLimitedSummaryModel)
    assert (model.provider, model.model_id) == ("ollama", "gemma3:27b")

    embedding = ai_registrar.create_embedding_model(config)
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
