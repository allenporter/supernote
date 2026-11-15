"""Tests for `supernote.server.ai.models.openai.backend`."""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from supernote.server.ai.base import AIError
from supernote.server.ai.models.ocr import InstrumentedOcrModel
from supernote.server.ai.models.openai.backend import (
    DEFAULT_BASE_URL,
    REQUEST_TIMEOUT,
    OpenAIBackend,
    _record_usage,
    create_openai_backend,
)
from supernote.server.ai.models.openai.ocr import OpenAIOcrModel
from supernote.server.config import ProviderConfig
from supernote.server.metrics import AIStage, track_ai_request

from .conftest import FakeOpenAIServer


def test_create_openai_backend() -> None:
    assert create_openai_backend({}, "openai") is None
    assert create_openai_backend({"openai": ProviderConfig()}, "openai") is None
    assert (
        create_openai_backend(
            {"openai": ProviderConfig(api_key=" ", base_url=" ")}, "openai"
        )
        is None
    )

    local = create_openai_backend(
        {"openai": ProviderConfig(base_url="http://localhost:11434/v1/")}, "openai"
    )
    assert isinstance(local, OpenAIBackend)
    assert local._base_url == "http://localhost:11434/v1"
    assert local._api_key is None
    assert local.provider == "openai"

    hosted = create_openai_backend(
        {"openai": ProviderConfig(api_key="sk-test")}, "openai"
    )
    assert isinstance(hosted, OpenAIBackend)
    assert hosted._base_url == DEFAULT_BASE_URL
    assert hosted._api_key == "sk-test"
    assert hosted.provider == "openai"


async def test_chat_completion(
    openai_backend: OpenAIBackend, fake_openai: FakeOpenAIServer
) -> None:
    text = await openai_backend.chat_completion(
        model="gemma", content=[{"type": "text", "text": "hello"}]
    )

    assert text == "transcribed text"
    assert fake_openai.requests == [
        (
            "/v1/chat/completions",
            "",
            {
                "model": "gemma",
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hello"}]}
                ],
            },
        )
    ]


async def test_chat_completion_null_content(
    openai_backend: OpenAIBackend, fake_openai: FakeOpenAIServer
) -> None:
    fake_openai.chat_content = None
    assert await openai_backend.chat_completion(model="gemma", content=[]) == ""


async def test_embeddings_with_api_key(
    openai_base_url: str, fake_openai: FakeOpenAIServer
) -> None:
    backend = OpenAIBackend(openai_base_url, api_key="sk-test", provider="openai")

    assert await backend.embeddings(model="embed", text="hello") == [0.1, 0.2, 0.3]
    assert fake_openai.requests == [
        ("/v1/embeddings", "Bearer sk-test", {"model": "embed", "input": "hello"})
    ]


async def test_http_error_raises_ai_error(
    openai_backend: OpenAIBackend,
    fake_openai: FakeOpenAIServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_openai.status = 404
    with caplog.at_level("ERROR"):
        with pytest.raises(AIError, match="HTTP 404: model not found"):
            await openai_backend.chat_completion(model="gemma", content=[])
    assert "HTTP 404: model not found" in caplog.text


async def test_malformed_response_raises_ai_error(
    openai_backend: OpenAIBackend, fake_openai: FakeOpenAIServer
) -> None:
    fake_openai.malformed = True
    with pytest.raises(AIError, match="error during chat_completion"):
        await openai_backend.chat_completion(model="gemma", content=[])
    with pytest.raises(AIError, match="error during embeddings"):
        await openai_backend.embeddings(model="embed", text="hello")


async def test_connection_error_raises_ai_error_and_records_metric() -> None:
    labels = {
        "provider": "openai",
        "model": "gemma",
        "stage": "ocr",
        "status": "failure",
    }
    before = REGISTRY.get_sample_value("supernote_ai_requests_total", labels)

    ocr_model = InstrumentedOcrModel(
        OpenAIOcrModel(
            OpenAIBackend("http://127.0.0.1:1/v1", provider="openai"), "gemma"
        )
    )
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
    assert REGISTRY.get_sample_value("supernote_ai_tokens_total", in_labels) is None
    assert REGISTRY.get_sample_value("supernote_ai_tokens_total", out_labels) == 130.0
    assert REGISTRY.get_sample_value("supernote_ai_tokens_total", think_labels) == 35.0


def test_create_openai_backend_named_entry() -> None:
    providers = {
        "openai": ProviderConfig(base_url="http://localhost:11434/v1"),
        "llamacpp": ProviderConfig(type="openai", base_url="http://localhost:8080/v1"),
    }
    backend = create_openai_backend(providers, "llamacpp")
    assert isinstance(backend, OpenAIBackend)
    assert backend._base_url == "http://localhost:8080/v1"
    assert backend.provider == "llamacpp"
    assert create_openai_backend(providers, "missing") is None
