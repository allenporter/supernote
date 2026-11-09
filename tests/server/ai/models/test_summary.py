"""Tests for `supernote.server.ai.models.summary`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from prometheus_client import REGISTRY

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import (
    ConcurrencyLimitedEmbeddingModel,
    EmbeddingTaskType,
    create_embedding_model,
)
from supernote.server.ai.models.fake.summary import FakeSummaryModel
from supernote.server.ai.models.summary import (
    ConcurrencyLimitedSummaryModel,
    InstrumentedSummaryModel,
    create_summary_model,
)
from supernote.server.config import (
    AiConfig,
    AuthConfig,
    ModelConfig,
    ProviderConfig,
    ServerConfig,
)


def test_create_summary_model_unconfigured(tmp_path: Path) -> None:
    config = ServerConfig(
        auth=AuthConfig(secret_key="secret"),
        storage_dir=str(tmp_path),
    )
    assert create_summary_model(config) is None


def test_create_summary_model_legacy_gemini() -> None:
    legacy_config = ServerConfig(gemini_api_key="test-key")
    model = create_summary_model(legacy_config)
    assert model is not None
    assert model.model_id == "gemini-3.5-flash-lite"


def test_create_summary_model_gemini_provider() -> None:
    ai_config = ServerConfig(
        ai=AiConfig(
            providers={"gemini": ProviderConfig(api_key="ai-key")},
            summary=ModelConfig(
                provider="gemini",
                model="gemini-custom-summary",
                max_concurrency=4,
            ),
        )
    )
    ai_model = create_summary_model(ai_config)
    assert ai_model is not None
    assert ai_model.model_id == "gemini-custom-summary"


def test_create_summary_model_openai_provider() -> None:
    ai_config = ServerConfig(
        ai=AiConfig(
            providers={"openai": ProviderConfig(base_url="http://localhost:11434/v1")},
            summary=ModelConfig(provider="openai", model="gemma", max_concurrency=1),
        )
    )
    ai_model = create_summary_model(ai_config)
    assert ai_model is not None
    assert ai_model.model_id == "gemma"


def test_create_summary_model_fake_provider() -> None:
    fake_config = ServerConfig(
        ai=AiConfig(
            summary=ModelConfig(
                provider="fake", model="fake-summary-custom", max_concurrency=2
            ),
        )
    )
    fake_model = create_summary_model(fake_config)
    assert fake_model is not None
    assert fake_model.model_id == "fake-summary-custom"


def test_create_summary_model_missing_provider_credentials() -> None:
    missing_provider_config = ServerConfig(
        ai=AiConfig(
            summary=ModelConfig(provider="gemini", model="gemini-3.6-flash"),
        )
    )
    assert create_summary_model(missing_provider_config) is None


def test_create_summary_model_unsupported_provider() -> None:
    unsupported_config = ServerConfig(
        ai=AiConfig(
            summary=ModelConfig(provider="unknown", model="some-model"),
        )
    )
    with pytest.raises(ValueError, match="Unsupported summary model provider"):
        create_summary_model(unsupported_config)


async def test_concurrency_limited_summary_model() -> None:
    wrapped = ConcurrencyLimitedSummaryModel(
        InstrumentedSummaryModel(FakeSummaryModel()), max_concurrency=2
    )
    result = await wrapped.summarize("TRANSCRIPT:\nHello")
    assert wrapped.provider == "fake"
    assert wrapped.model_id == "fake-summary-v1"
    assert len(result.segments) == 1


async def test_instrumented_summary_model_records_success_and_failure() -> None:
    model = FakeSummaryModel(model_id="instr-summary-v1", provider="fake-instr")
    wrapped = InstrumentedSummaryModel(model)
    ok_labels = {
        "provider": "fake-instr",
        "model": "instr-summary-v1",
        "stage": "summary",
        "status": "success",
    }
    fail_labels = {**ok_labels, "status": "failure"}
    before_ok = REGISTRY.get_sample_value("supernote_ai_requests_total", ok_labels)
    before_fail = REGISTRY.get_sample_value("supernote_ai_requests_total", fail_labels)
    assert before_ok is not None
    assert before_fail is not None

    await wrapped.summarize("TRANSCRIPT:\nHello")
    model.error = AIError("boom")
    with pytest.raises(AIError, match="boom"):
        await wrapped.summarize("TRANSCRIPT:\nHello")

    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", ok_labels)
        == before_ok + 1.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", fail_labels)
        == before_fail + 1.0
    )


async def test_create_summary_model_named_openai_providers(
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
    model = create_summary_model(config)
    assert isinstance(model, ConcurrencyLimitedSummaryModel)
    assert (model.provider, model.model_id) == ("ollama", "gemma3:27b")

    embedding = create_embedding_model(config)
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


def test_create_summary_model_unknown_provider_type() -> None:
    config = ServerConfig(
        ai=AiConfig(
            providers={"mine": ProviderConfig(type="unknown")},
            summary=ModelConfig(provider="mine", model="some-model"),
        )
    )
    with pytest.raises(ValueError, match="provider type: 'unknown'"):
        create_summary_model(config)
