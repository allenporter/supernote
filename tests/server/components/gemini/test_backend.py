"""Tests for `supernote.server.components.gemini.backend`."""

from __future__ import annotations

import json

import pytest
from aiohttp import web
from prometheus_client import REGISTRY
from pytest_aiohttp import AiohttpServer

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import EmbeddingTaskType
from supernote.server.components.gemini.backend import GeminiBackend, _positive_int
from supernote.server.config import ModelConfig, ProviderConfig

from .conftest import FakeGeminiServer, LoadGeminiModels


@pytest.mark.parametrize(
    "providers",
    [
        {},
        {"gemini": ProviderConfig(api_key="  ")},
        {"work": ProviderConfig(type="gemini", api_key="work-key")},
    ],
)
async def test_gemini_missing_blank_or_mismatched_provider_disables_all_models(
    load_gemini_models: LoadGeminiModels,
    providers: dict[str, ProviderConfig],
) -> None:
    ocr, summary, embedding = await load_gemini_models(
        providers=providers,
        ocr=ModelConfig(provider="gemini", model="gemini-2.0-flash"),
        summary=ModelConfig(provider="gemini", model="gemini-2.0-flash"),
        embedding=ModelConfig(provider="gemini", model="text-embedding-004"),
    )
    assert (ocr, summary, embedding) == (None, None, None)


async def test_gemini_backend_api_error_raises_ai_error(
    load_gemini_models: LoadGeminiModels,
    fake_gemini: FakeGeminiServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ocr_model, _, embedding_model = await load_gemini_models(
        ocr=ModelConfig(provider="gemini", model="gemini-2.0-flash"),
        embedding=ModelConfig(provider="gemini", model="text-embedding-004"),
    )
    assert ocr_model is not None and embedding_model is not None

    fake_gemini.status = 404
    with caplog.at_level("ERROR"):
        with pytest.raises(AIError, match="404"):
            await ocr_model.extract_text(b"png", "hello")
    assert "Gemini API error during generate_content" in caplog.text

    with pytest.raises(AIError, match="404"):
        await embedding_model.embed("hello", EmbeddingTaskType.RETRIEVAL_QUERY)


async def test_gemini_backend_malformed_response_raises_ai_error(
    load_gemini_models: LoadGeminiModels,
    fake_gemini: FakeGeminiServer,
) -> None:
    ocr_model, _, embedding_model = await load_gemini_models(
        ocr=ModelConfig(provider="gemini", model="gemini-2.0-flash"),
        embedding=ModelConfig(provider="gemini", model="text-embedding-004"),
    )
    assert ocr_model is not None and embedding_model is not None

    fake_gemini.malformed = True
    with pytest.raises(
        AIError, match=r"Unexpected error calling Gemini API \(generate_content\)"
    ):
        await ocr_model.extract_text(b"png", "hello")
    with pytest.raises(
        AIError, match=r"Unexpected error calling Gemini API \(embed_content\)"
    ):
        await embedding_model.embed("hello", EmbeddingTaskType.RETRIEVAL_QUERY)


async def test_gemini_connection_error_raises_ai_error_and_records_metric(
    load_gemini_models: LoadGeminiModels,
) -> None:
    labels = {
        "provider": "gemini",
        "model": "gemini-2.0-flash",
        "stage": "ocr",
        "status": "failure",
    }
    before = REGISTRY.get_sample_value("supernote_ai_requests_total", labels)

    ocr_model, _, _ = await load_gemini_models(
        providers={
            "gemini": ProviderConfig(api_key="fake-key", base_url="http://127.0.0.1:1")
        },
        ocr=ModelConfig(provider="gemini", model="gemini-2.0-flash"),
    )
    assert ocr_model is not None
    with pytest.raises(
        AIError, match=r"Unexpected error calling Gemini API \(generate_content\)"
    ):
        await ocr_model.extract_text(b"png", "hello")

    after = REGISTRY.get_sample_value("supernote_ai_requests_total", labels)
    assert after == (before or 0.0) + 1.0


async def test_gemini_embed_content_ignores_non_finite_token_statistics(
    aiohttp_server: AiohttpServer,
    load_gemini_models: LoadGeminiModels,
) -> None:
    """A non-finite `statistics.tokenCount` never fails an otherwise valid call."""

    async def handle_batch_embed(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "embeddings": [
                    {"values": [0.1, 0.2], "statistics": {"tokenCount": float("nan")}}
                ]
            }
        )

    app = web.Application()
    app.router.add_post("/v1beta/models/{model}:batchEmbedContents", handle_batch_embed)
    server = await aiohttp_server(app)

    _, _, embedding_model = await load_gemini_models(
        providers={
            "gemini": ProviderConfig(api_key="key", base_url=str(server.make_url("/")))
        },
        embedding=ModelConfig(provider="gemini", model="nan-embed"),
    )
    assert embedding_model is not None

    labels = {
        "provider": "gemini",
        "model": "nan-embed",
        "stage": "embedding_doc",
        "token_type": "input",
    }
    before = REGISTRY.get_sample_value("supernote_ai_tokens_total", labels)
    vec = await embedding_model.embed("hello", EmbeddingTaskType.RETRIEVAL_DOCUMENT)
    assert vec == [0.1, 0.2]
    assert REGISTRY.get_sample_value("supernote_ai_tokens_total", labels) == before


def test_gemini_backend_handle_api_errors_preserves_ai_error_and_unexpected_bugs() -> (
    None
):
    backend = GeminiBackend(api_key="test-key", provider="gemini")
    with pytest.raises(AIError, match=r"^already wrapped$"):
        with backend._handle_api_errors("generate_content"):
            raise AIError("already wrapped")

    with pytest.raises(AttributeError, match="unexpected bug"):
        with backend._handle_api_errors("generate_content"):
            raise AttributeError("unexpected bug")


def test_positive_int_filters_invalid_values() -> None:
    assert _positive_int(True) == 0
    assert _positive_int(-5) == 0
    assert _positive_int("12") == 0
    assert _positive_int(18) == 18


async def test_gemini_generate_content_sums_only_positive_prompt_tokens(
    aiohttp_server: AiohttpServer,
    load_gemini_models: LoadGeminiModels,
) -> None:
    """Prompt + tool-use prompt tokens sum only positive `int` values."""

    async def handle_generate(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "candidates": [
                    {"content": {"parts": [{"text": json.dumps({"segments": []})}]}}
                ],
                "usageMetadata": {
                    "promptTokenCount": -5,
                    "toolUsePromptTokenCount": 18,
                    "candidatesTokenCount": 0,
                    "thoughtsTokenCount": 7,
                },
            }
        )

    app = web.Application()
    app.router.add_post("/v1beta/models/{model}:generateContent", handle_generate)
    server = await aiohttp_server(app)

    _, summary_model, _ = await load_gemini_models(
        providers={
            "gemini": ProviderConfig(api_key="key", base_url=str(server.make_url("/")))
        },
        summary=ModelConfig(provider="gemini", model="sum-guard-model"),
    )
    assert summary_model is not None

    in_labels = {
        "provider": "gemini",
        "model": "sum-guard-model",
        "stage": "summary",
        "token_type": "input",
    }
    out_labels = {**in_labels, "token_type": "output"}
    think_labels = {**in_labels, "token_type": "thinking"}

    before_in = REGISTRY.get_sample_value("supernote_ai_tokens_total", in_labels) or 0.0
    before_out = (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", out_labels) or 0.0
    )
    before_think = (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", think_labels) or 0.0
    )

    await summary_model.summarize("hi")

    assert (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", in_labels)
        == before_in + 18.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", out_labels) == before_out
    )
    assert (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", think_labels)
        == before_think + 7.0
    )
