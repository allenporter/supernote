"""Fixtures for OpenAI-compatible component tests: a fake HTTP server and component-wired models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import pytest
from aiohttp import web
from pytest_aiohttp import AiohttpServer

from supernote.server.ai.models.embedding import EmbeddingModel
from supernote.server.ai.models.ocr import OcrModel
from supernote.server.ai.models.summary import SummaryModel
from supernote.server.components.ai import (
    EMBEDDING_MODEL_KEY,
    OCR_MODEL_KEY,
    SUMMARY_MODEL_KEY,
)
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig
from supernote.server.core import ServerCore
from tests.server.components.conftest import LoadComponents


@dataclass
class FakeOpenAIServer:
    """Records requests and replies with configurable responses."""

    requests: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    status: int = 200
    malformed: bool = False
    chat_content: str | None = "transcribed text"
    omit_chat_content: bool = False
    embedding: list[float] = field(default_factory=lambda: [0.1, 0.2, 0.3])

    async def _record(self, request: web.Request) -> None:
        self.requests.append(
            (
                request.path,
                request.headers.get("Authorization", ""),
                await request.json(),
            )
        )

    async def chat(self, request: web.Request) -> web.Response:
        await self._record(request)
        if self.status != 200:
            return web.Response(status=self.status, text="model not found")
        if self.malformed:
            return web.json_response({"choices": []})
        message: dict[str, Any] = (
            {} if self.omit_chat_content else {"content": self.chat_content}
        )
        return web.json_response({"choices": [{"message": message}]})

    async def embeddings(self, request: web.Request) -> web.Response:
        await self._record(request)
        if self.status != 200:
            return web.Response(status=self.status, text="model not found")
        if self.malformed:
            return web.json_response({"data": []})
        return web.json_response({"data": [{"embedding": self.embedding}]})


class LoadOpenAIModels(Protocol):
    """Callable fixture protocol for booting `ai` + `openai` against a base URL."""

    async def __call__(
        self,
        *,
        ocr: ModelConfig | None = None,
        summary: ModelConfig | None = None,
        embedding: ModelConfig | None = None,
        providers: dict[str, ProviderConfig] | None = None,
    ) -> tuple[OcrModel | None, SummaryModel | None, EmbeddingModel | None]: ...


@pytest.fixture
def fake_openai() -> FakeOpenAIServer:
    return FakeOpenAIServer()


@pytest.fixture
async def openai_base_url(
    aiohttp_server: AiohttpServer, fake_openai: FakeOpenAIServer
) -> str:
    app = web.Application()
    app.router.add_post("/v1/chat/completions", fake_openai.chat)
    app.router.add_post("/v1/embeddings", fake_openai.embeddings)
    server = await aiohttp_server(app)
    return str(server.make_url("/v1"))


@pytest.fixture
def load_openai_models(
    component_core: ServerCore,
    load_components: LoadComponents,
    openai_base_url: str,
) -> LoadOpenAIModels:
    """Return a loader that configures `AiConfig` and boots `ai` + `openai`."""

    async def _load(
        *,
        ocr: ModelConfig | None = None,
        summary: ModelConfig | None = None,
        embedding: ModelConfig | None = None,
        providers: dict[str, ProviderConfig] | None = None,
    ) -> tuple[OcrModel | None, SummaryModel | None, EmbeddingModel | None]:
        component_core.config.ai = AiConfig(
            providers=(
                providers
                if providers is not None
                else {"openai": ProviderConfig(base_url=openai_base_url)}
            ),
            ocr=ocr,
            summary=summary,
            embedding=embedding,
        )
        await load_components("ai", "openai")
        return (
            component_core.app[OCR_MODEL_KEY],
            component_core.app[SUMMARY_MODEL_KEY],
            component_core.app[EMBEDDING_MODEL_KEY],
        )

    return _load


@pytest.fixture
async def openai_ocr_model(load_openai_models: LoadOpenAIModels) -> OcrModel:
    ocr, _, _ = await load_openai_models(
        ocr=ModelConfig(provider="openai", model="gemma-vision")
    )
    assert ocr is not None
    return ocr


@pytest.fixture
async def openai_summary_model(load_openai_models: LoadOpenAIModels) -> SummaryModel:
    _, summary, _ = await load_openai_models(
        summary=ModelConfig(provider="openai", model="gemma")
    )
    assert summary is not None
    return summary


@pytest.fixture
async def openai_embedding_model(
    load_openai_models: LoadOpenAIModels,
) -> EmbeddingModel:
    _, _, embedding = await load_openai_models(
        embedding=ModelConfig(provider="openai", model="nomic-embed-text")
    )
    assert embedding is not None
    return embedding
