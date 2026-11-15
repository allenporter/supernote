"""Tests for `supernote.server.ai.models.gemini.backend`."""

from __future__ import annotations

from typing import Any

import pytest
from aiohttp import web
from prometheus_client import REGISTRY

from supernote.server.ai.base import AIError
from supernote.server.ai.models.gemini.backend import (
    GeminiBackend,
    _positive_int,
    create_gemini_backend,
)
from supernote.server.ai.models.gemini.ocr import GeminiOcrModel
from supernote.server.ai.models.ocr import InstrumentedOcrModel
from supernote.server.config import ProviderConfig
from supernote.server.metrics import AIStage, track_ai_request

from .conftest import FakeGeminiServer


def test_create_gemini_backend() -> None:
    assert create_gemini_backend({}, "gemini") is None
    assert (
        create_gemini_backend({"gemini": ProviderConfig(api_key="  ")}, "gemini")
        is None
    )

    backend = create_gemini_backend(
        {
            "gemini": ProviderConfig(
                api_key="valid-key", base_url="http://localhost:8080"
            )
        },
        "gemini",
    )
    assert isinstance(backend, GeminiBackend)
    assert backend._api_key == "valid-key"
    assert backend._base_url == "http://localhost:8080"
    assert backend.provider == "gemini"


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


async def test_gemini_connection_error_raises_ai_error_and_records_metric() -> None:
    labels = {
        "provider": "gemini",
        "model": "gemini-2.0-flash",
        "stage": "ocr",
        "status": "failure",
    }
    before = REGISTRY.get_sample_value("supernote_ai_requests_total", labels)

    backend = GeminiBackend(
        api_key="fake-key",
        base_url="http://127.0.0.1:1",
        provider="gemini",
    )
    ocr_model = InstrumentedOcrModel(GeminiOcrModel(backend, "gemini-2.0-flash"))
    with pytest.raises(
        AIError, match=r"Unexpected error calling Gemini API \(generate_content\)"
    ):
        await ocr_model.extract_text(b"png", "hello")

    after = REGISTRY.get_sample_value("supernote_ai_requests_total", labels)
    assert after == (before or 0.0) + 1.0


async def test_gemini_embed_content_ignores_non_finite_token_statistics(
    aiohttp_server: Any,
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
    backend = GeminiBackend(
        api_key="key",
        base_url=str(server.make_url("/")),
        provider="gemini",
    )

    labels = {
        "provider": "gemini",
        "model": "nan-embed",
        "stage": "embedding_doc",
        "token_type": "input",
    }
    before = REGISTRY.get_sample_value("supernote_ai_tokens_total", labels)
    with track_ai_request(
        provider="gemini", model="nan-embed", stage=AIStage.EMBEDDING_DOCUMENT
    ):
        response = await backend.embed_content(model="nan-embed", contents="hello")
    assert response.embeddings
    assert REGISTRY.get_sample_value("supernote_ai_tokens_total", labels) == before


def test_gemini_backend_handle_api_errors_preserves_ai_error_and_unexpected_bugs(
    gemini_backend: GeminiBackend,
) -> None:
    with pytest.raises(AIError, match=r"^already wrapped$"):
        with gemini_backend._handle_api_errors("generate_content"):
            raise AIError("already wrapped")

    with pytest.raises(AttributeError, match="unexpected bug"):
        with gemini_backend._handle_api_errors("generate_content"):
            raise AttributeError("unexpected bug")


def test_create_gemini_backend_named_entry() -> None:
    providers = {"work": ProviderConfig(type="gemini", api_key="work-key")}
    backend = create_gemini_backend(providers, "work")
    assert isinstance(backend, GeminiBackend)
    assert backend._api_key == "work-key"
    assert backend.provider == "work"
    assert create_gemini_backend(providers, "gemini") is None


async def test_gemini_generate_content_sums_only_positive_prompt_tokens(
    aiohttp_server: Any,
) -> None:
    """Prompt + tool-use prompt tokens sum only positive `int` values (ignoring negatives/bools)."""
    assert _positive_int(True) == 0
    assert _positive_int(-5) == 0
    assert _positive_int("12") == 0
    assert _positive_int(18) == 18

    async def handle_generate(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
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
    backend = GeminiBackend(
        api_key="key",
        base_url=str(server.make_url("/")),
        provider="gemini",
    )

    in_labels = {
        "provider": "gemini",
        "model": "sum-guard-model",
        "stage": "summary",
        "token_type": "input",
    }
    out_labels = {**in_labels, "token_type": "output"}
    think_labels = {**in_labels, "token_type": "thinking"}

    with track_ai_request(
        provider="gemini", model="sum-guard-model", stage=AIStage.SUMMARY
    ):
        await backend.generate_content(model="sum-guard-model", contents="hi")

    assert REGISTRY.get_sample_value("supernote_ai_tokens_total", in_labels) == 18.0
    assert REGISTRY.get_sample_value("supernote_ai_tokens_total", out_labels) is None
    assert REGISTRY.get_sample_value("supernote_ai_tokens_total", think_labels) == 7.0
