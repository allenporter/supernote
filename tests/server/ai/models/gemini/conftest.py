"""Fixtures for Gemini model tests: a fake Gemini HTTP server."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from supernote.server.ai.models.gemini.backend import GeminiBackend

AiohttpServer = Callable[[web.Application], Awaitable[TestServer]]


@dataclass
class FakeGeminiServer:
    """Records requests and replies with configurable Gemini REST responses."""

    requests: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    status: int = 200
    malformed: bool = False
    text: str | None = "Handwritten text content"
    embedding: list[float] | None = field(default_factory=lambda: [0.1, 0.2, 0.3])

    async def _record(self, request: web.Request) -> None:
        self.requests.append(
            (
                request.path,
                request.headers.get("x-goog-api-key", ""),
                await request.json(),
            )
        )

    def _error_response(self) -> web.Response:
        return web.json_response(
            {
                "error": {
                    "code": self.status,
                    "message": "model not found",
                    "status": "NOT_FOUND",
                }
            },
            status=self.status,
        )

    async def generate_content(self, request: web.Request) -> web.Response:
        await self._record(request)
        if self.status != 200:
            return self._error_response()
        if self.malformed:
            return web.Response(
                status=200, body=b"not-json", content_type="application/json"
            )
        if self.text is None:
            return web.json_response({"candidates": []})
        return web.json_response(
            {"candidates": [{"content": {"parts": [{"text": self.text}]}}]}
        )

    async def batch_embed_contents(self, request: web.Request) -> web.Response:
        await self._record(request)
        if self.status != 200:
            return self._error_response()
        if self.malformed:
            return web.Response(
                status=200, body=b"not-json", content_type="application/json"
            )
        if self.embedding is None:
            return web.json_response({"embeddings": []})
        return web.json_response({"embeddings": [{"values": self.embedding}]})


@pytest.fixture
def fake_gemini() -> FakeGeminiServer:
    return FakeGeminiServer()


@pytest.fixture
async def gemini_base_url(
    aiohttp_server: AiohttpServer, fake_gemini: FakeGeminiServer
) -> str:
    app = web.Application()
    app.router.add_post(
        "/v1beta/models/{model}:generateContent", fake_gemini.generate_content
    )
    app.router.add_post(
        "/v1beta/models/{model}:batchEmbedContents",
        fake_gemini.batch_embed_contents,
    )
    server = await aiohttp_server(app)
    return str(server.make_url("/"))


@pytest.fixture
def gemini_backend(gemini_base_url: str) -> GeminiBackend:
    return GeminiBackend(
        api_key="test-key",
        base_url=gemini_base_url,
        provider="gemini",
    )
