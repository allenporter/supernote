"""Fixtures for OpenAI-compatible model tests: a fake HTTP server."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from supernote.server.ai.models.openai.backend import OpenAIBackend

AiohttpServer = Callable[[web.Application], Awaitable[TestServer]]


@dataclass
class FakeOpenAIServer:
    """Records requests and replies with configurable responses."""

    requests: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    status: int = 200
    malformed: bool = False
    chat_content: str | None = "transcribed text"
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
        return web.json_response(
            {"choices": [{"message": {"content": self.chat_content}}]}
        )

    async def embeddings(self, request: web.Request) -> web.Response:
        await self._record(request)
        if self.status != 200:
            return web.Response(status=self.status, text="model not found")
        if self.malformed:
            return web.json_response({"data": []})
        return web.json_response({"data": [{"embedding": self.embedding}]})


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
def openai_backend(openai_base_url: str) -> OpenAIBackend:
    return OpenAIBackend(openai_base_url)
