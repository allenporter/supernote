"""Tests for `supernote.server.ai.models.gemini.backend`."""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from supernote.server.ai.base import AIError
from supernote.server.ai.models.gemini.backend import (
    GeminiBackend,
    create_gemini_backend,
)
from supernote.server.config import ProviderConfig

from .conftest import FakeGeminiServer


def test_create_gemini_backend() -> None:
    assert create_gemini_backend({}) is None
    assert create_gemini_backend({"gemini": ProviderConfig(api_key="  ")}) is None

    backend = create_gemini_backend(
        {
            "gemini": ProviderConfig(
                api_key="valid-key", base_url="http://localhost:8080"
            )
        }
    )
    assert isinstance(backend, GeminiBackend)
    assert backend._api_key == "valid-key"
    assert backend._base_url == "http://localhost:8080"


async def test_gemini_backend_api_error_raises_ai_error(
    gemini_backend: GeminiBackend,
    fake_gemini: FakeGeminiServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_gemini.status = 404
    with caplog.at_level("ERROR"):
        with pytest.raises(AIError, match="404"):
            await gemini_backend.generate_content(
                model="gemini-2.0-flash", contents="hello"
            )
    assert "Gemini API error during generate_content" in caplog.text

    with pytest.raises(AIError, match="404"):
        await gemini_backend.embed_content(model="text-embedding-004", contents="hello")


async def test_gemini_backend_malformed_response_raises_ai_error(
    gemini_backend: GeminiBackend,
    fake_gemini: FakeGeminiServer,
) -> None:
    fake_gemini.malformed = True
    with pytest.raises(
        AIError, match=r"Unexpected error calling Gemini API \(generate_content\)"
    ):
        await gemini_backend.generate_content(
            model="gemini-2.0-flash", contents="hello"
        )
    with pytest.raises(
        AIError, match=r"Unexpected error calling Gemini API \(embed_content\)"
    ):
        await gemini_backend.embed_content(model="text-embedding-004", contents="hello")


async def test_gemini_backend_connection_error_raises_ai_error_and_records_metric() -> (
    None
):
    labels = {"operation": "generate_content", "status": "failure"}
    before = REGISTRY.get_sample_value("supernote_gemini_api_calls_total", labels)

    backend = GeminiBackend(api_key="fake-key", base_url="http://127.0.0.1:1")
    with pytest.raises(
        AIError, match=r"Unexpected error calling Gemini API \(generate_content\)"
    ):
        await backend.generate_content(model="gemini-2.0-flash", contents="hello")

    after = REGISTRY.get_sample_value("supernote_gemini_api_calls_total", labels)
    assert after == (before or 0.0) + 1.0


def test_gemini_backend_track_api_call_preserves_ai_error_and_unexpected_bugs(
    gemini_backend: GeminiBackend,
) -> None:
    with pytest.raises(AIError, match=r"^already wrapped$"):
        with gemini_backend._track_api_call("generate_content"):
            raise AIError("already wrapped")

    with pytest.raises(AttributeError, match="unexpected bug"):
        with gemini_backend._track_api_call("generate_content"):
            raise AttributeError("unexpected bug")


def test_create_gemini_backend_named_entry() -> None:
    providers = {"work": ProviderConfig(type="gemini", api_key="work-key")}
    backend = create_gemini_backend(providers, "work")
    assert isinstance(backend, GeminiBackend)
    assert backend._api_key == "work-key"
    assert create_gemini_backend(providers) is None
