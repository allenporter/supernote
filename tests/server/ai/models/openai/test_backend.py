"""Tests for `supernote.server.ai.models.openai.backend`."""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from supernote.server.ai.base import AIError
from supernote.server.ai.models.openai.backend import (
    DEFAULT_BASE_URL,
    OpenAIBackend,
    create_openai_backend,
)
from supernote.server.config import ProviderConfig

from .conftest import FakeOpenAIServer


def test_create_openai_backend() -> None:
    assert create_openai_backend({}) is None
    assert create_openai_backend({"openai": ProviderConfig()}) is None
    assert (
        create_openai_backend({"openai": ProviderConfig(api_key=" ", base_url=" ")})
        is None
    )

    local = create_openai_backend(
        {"openai": ProviderConfig(base_url="http://localhost:11434/v1/")}
    )
    assert isinstance(local, OpenAIBackend)
    assert local._base_url == "http://localhost:11434/v1"
    assert local._api_key is None

    hosted = create_openai_backend({"openai": ProviderConfig(api_key="sk-test")})
    assert isinstance(hosted, OpenAIBackend)
    assert hosted._base_url == DEFAULT_BASE_URL
    assert hosted._api_key == "sk-test"


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
    backend = OpenAIBackend(openai_base_url, api_key="sk-test")

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
    labels = {"operation": "chat_completion", "status": "failure"}
    before = REGISTRY.get_sample_value("supernote_openai_api_calls_total", labels)

    with pytest.raises(AIError, match="during chat_completion"):
        await OpenAIBackend("http://127.0.0.1:1/v1").chat_completion(
            model="gemma", content=[]
        )

    after = REGISTRY.get_sample_value("supernote_openai_api_calls_total", labels)
    assert after == (before or 0.0) + 1.0


def test_create_openai_backend_named_entry() -> None:
    providers = {
        "openai": ProviderConfig(base_url="http://localhost:11434/v1"),
        "llamacpp": ProviderConfig(type="openai", base_url="http://localhost:8080/v1"),
    }
    backend = create_openai_backend(providers, "llamacpp")
    assert isinstance(backend, OpenAIBackend)
    assert backend._base_url == "http://localhost:8080/v1"
    assert create_openai_backend(providers, "missing") is None
