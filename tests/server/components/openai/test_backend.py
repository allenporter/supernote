"""Tests for `supernote.server.components.openai.backend`."""

from __future__ import annotations

from unittest.mock import patch

import aiohttp
import pytest
from prometheus_client import REGISTRY

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import EmbeddingTaskType
from supernote.server.ai.models.ocr import OcrModel
from supernote.server.components.openai.backend import (
    REQUEST_TIMEOUT,
    OpenAIBackend,
    _record_usage,
)
from supernote.server.config import ModelConfig, ProviderConfig
from supernote.server.metrics import AIStage, track_ai_request

from .conftest import FakeOpenAIServer, LoadOpenAIModels


@pytest.mark.parametrize(
    "providers",
    [
        {},
        {"openai": ProviderConfig()},
        {"openai": ProviderConfig(api_key=" ", base_url=" ")},
    ],
)
async def test_openai_missing_or_blank_provider_disables_all_models(
    load_openai_models: LoadOpenAIModels,
    providers: dict[str, ProviderConfig],
) -> None:
    ocr, summary, embedding = await load_openai_models(
        providers=providers,
        ocr=ModelConfig(provider="openai", model="gemma"),
        summary=ModelConfig(provider="openai", model="gemma"),
        embedding=ModelConfig(provider="openai", model="nomic-embed-text"),
    )
    assert (ocr, summary, embedding) == (None, None, None)


async def test_openai_trailing_slash_base_url_normalized(
    load_openai_models: LoadOpenAIModels,
    openai_base_url: str,
    fake_openai: FakeOpenAIServer,
) -> None:
    ocr, _, _ = await load_openai_models(
        providers={"openai": ProviderConfig(base_url=f"{openai_base_url}/")},
        ocr=ModelConfig(provider="openai", model="gemma"),
    )
    assert ocr is not None
    assert await ocr.extract_text(b"png", "hi") == "transcribed text"
    assert fake_openai.requests[0][0] == "/v1/chat/completions"
    assert fake_openai.requests[0][1] == ""


async def test_openai_defaults_to_hosted_url_with_api_key(
    load_openai_models: LoadOpenAIModels,
    openai_base_url: str,
    fake_openai: FakeOpenAIServer,
) -> None:
    with patch(
        "supernote.server.components.openai.backend.DEFAULT_BASE_URL", openai_base_url
    ):
        ocr, _, _ = await load_openai_models(
            providers={"openai": ProviderConfig(api_key="sk-test")},
            ocr=ModelConfig(provider="openai", model="gemma"),
        )
    assert ocr is not None
    assert ocr.provider == "openai"
    assert await ocr.extract_text(b"png", "hi") == "transcribed text"
    assert fake_openai.requests[0][0] == "/v1/chat/completions"
    assert fake_openai.requests[0][1] == "Bearer sk-test"


async def test_chat_completion_null_and_omitted_content(
    openai_ocr_model: OcrModel, fake_openai: FakeOpenAIServer
) -> None:
    fake_openai.chat_content = None
    assert await openai_ocr_model.extract_text(b"png", "prompt") == ""

    fake_openai.omit_chat_content = True
    assert await openai_ocr_model.extract_text(b"png", "prompt") == ""


async def test_embeddings_with_api_key(
    load_openai_models: LoadOpenAIModels,
    openai_base_url: str,
    fake_openai: FakeOpenAIServer,
) -> None:
    _, _, embedding_model = await load_openai_models(
        providers={
            "openai": ProviderConfig(base_url=openai_base_url, api_key="sk-test")
        },
        embedding=ModelConfig(provider="openai", model="embed"),
    )
    assert embedding_model is not None

    assert await embedding_model.embed("hello", EmbeddingTaskType.RETRIEVAL_QUERY) == [
        0.1,
        0.2,
        0.3,
    ]
    assert fake_openai.requests == [
        ("/v1/embeddings", "Bearer sk-test", {"model": "embed", "input": "hello"})
    ]


async def test_http_error_raises_ai_error(
    openai_ocr_model: OcrModel,
    fake_openai: FakeOpenAIServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_openai.status = 404
    with caplog.at_level("ERROR"):
        with pytest.raises(AIError, match="HTTP 404: model not found"):
            await openai_ocr_model.extract_text(b"png", "prompt")
    assert "HTTP 404: model not found" in caplog.text


async def test_malformed_response_raises_ai_error(
    load_openai_models: LoadOpenAIModels,
    fake_openai: FakeOpenAIServer,
) -> None:
    ocr_model, _, embedding_model = await load_openai_models(
        ocr=ModelConfig(provider="openai", model="gemma"),
        embedding=ModelConfig(provider="openai", model="embed"),
    )
    assert ocr_model is not None and embedding_model is not None

    fake_openai.malformed = True
    with pytest.raises(AIError, match="error during chat_completion"):
        await ocr_model.extract_text(b"png", "prompt")
    with pytest.raises(AIError, match="error during embeddings"):
        await embedding_model.embed("hello", EmbeddingTaskType.RETRIEVAL_QUERY)


async def test_connection_error_raises_ai_error_and_records_metric(
    load_openai_models: LoadOpenAIModels,
) -> None:
    labels = {
        "provider": "openai",
        "model": "gemma",
        "stage": "ocr",
        "status": "failure",
    }
    before = REGISTRY.get_sample_value("supernote_ai_requests_total", labels)

    ocr_model, _, _ = await load_openai_models(
        providers={"openai": ProviderConfig(base_url="http://127.0.0.1:1/v1")},
        ocr=ModelConfig(provider="openai", model="gemma"),
    )
    assert ocr_model is not None
    with pytest.raises(AIError, match="during chat_completion"):
        await ocr_model.extract_text(b"png", "prompt")

    after = REGISTRY.get_sample_value("supernote_ai_requests_total", labels)
    assert after == (before or 0.0) + 1.0


def test_record_usage_ignores_invalid_shapes() -> None:
    """Malformed `usage` payloads are ignored without raising or skewing subtraction."""
    assert REQUEST_TIMEOUT.total == 600
    in_labels = {
        "provider": "shape-test",
        "model": "m",
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

    with track_ai_request(provider="shape-test", model="m", stage=AIStage.SUMMARY):
        _record_usage(None, provider="shape-test")
        _record_usage({"usage": None}, provider="shape-test")
        _record_usage({"usage": "invalid"}, provider="shape-test")
        _record_usage(
            {"usage": {"prompt_tokens": "12", "completion_tokens": None}},
            provider="shape-test",
        )
        # `bool` is an `int` subclass; negative `reasoning_tokens` must not inflate `output`.
        _record_usage(
            {
                "usage": {
                    "completion_tokens": 60,
                    "completion_tokens_details": {"reasoning_tokens": True},
                }
            },
            provider="shape-test",
        )
        _record_usage(
            {
                "usage": {
                    "completion_tokens": 40,
                    "completion_tokens_details": {"reasoning_tokens": -10},
                }
            },
            provider="shape-test",
        )
        # Float counts from proxies subtract cleanly; `reasoning > completion` clamps to 0.
        _record_usage(
            {
                "usage": {
                    "completion_tokens": 50.0,
                    "completion_tokens_details": {"reasoning_tokens": 20.0},
                }
            },
            provider="shape-test",
        )
        _record_usage(
            {
                "usage": {
                    "completion_tokens": 5,
                    "completion_tokens_details": {"reasoning_tokens": 15},
                }
            },
            provider="shape-test",
        )

    assert (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", in_labels) or 0.0
    ) == before_in
    assert (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", out_labels)
        == before_out + 130.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", think_labels)
        == before_think + 35.0
    )


async def test_openai_backend_reuses_injected_client_session_across_calls(
    openai_base_url: str,
    fake_openai: FakeOpenAIServer,
) -> None:
    """Back-to-back calls reuse the constructor-injected `aiohttp.ClientSession`."""
    async with aiohttp.ClientSession() as session:
        backend = OpenAIBackend(openai_base_url, provider="openai", session=session)

        reply = await backend.chat_completion(
            model="gemma", content=[{"type": "text", "text": "hi"}]
        )
        assert reply == "transcribed text"
        assert not session.closed

        vec = await backend.embeddings(model="embed", text="hello")
        assert vec == [0.1, 0.2, 0.3]
        assert not session.closed
        assert len(fake_openai.requests) == 2
        assert backend._session is session


async def test_openai_backend_standalone_fallback_without_injected_session(
    openai_base_url: str,
    fake_openai: FakeOpenAIServer,
) -> None:
    """Standalone callers with `session=None` use a request-scoped session without leaking."""
    backend = OpenAIBackend(openai_base_url, provider="openai")
    reply = await backend.chat_completion(
        model="gemma", content=[{"type": "text", "text": "standalone"}]
    )
    assert reply == "transcribed text"
    assert backend._session is None
    assert len(fake_openai.requests) == 1
