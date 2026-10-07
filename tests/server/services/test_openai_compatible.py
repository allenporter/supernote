import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from prometheus_client import REGISTRY

from supernote.server.services.llm import LLMError
from supernote.server.services.openai_compatible import OpenAICompatibleService

AiohttpServer = Callable[[web.Application], Awaitable[TestServer]]


@dataclass
class FakeOpenAIServer:
    """Records requests and replies with a configurable response."""

    requests: list[tuple[str, dict[str, str], dict[str, Any]]] = field(
        default_factory=list
    )
    status: int = 200
    chat_response: Any = field(
        default_factory=lambda: {"choices": [{"message": {"content": "hello"}}]}
    )
    embedding_response: Any = field(
        default_factory=lambda: {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
    )

    async def _handle(self, request: web.Request, body: Any) -> web.Response:
        self.requests.append(
            (
                request.path,
                {"Authorization": request.headers.get("Authorization", "")},
                await request.json(),
            )
        )
        if self.status != 200:
            return web.Response(status=self.status, text="model not found")
        return web.json_response(body)

    async def chat(self, request: web.Request) -> web.Response:
        return await self._handle(request, self.chat_response)

    async def embeddings(self, request: web.Request) -> web.Response:
        return await self._handle(request, self.embedding_response)


@pytest.fixture
def fake_server() -> FakeOpenAIServer:
    return FakeOpenAIServer()


@pytest.fixture
async def base_url(aiohttp_server: AiohttpServer, fake_server: FakeOpenAIServer) -> str:
    app = web.Application()
    app.router.add_post("/v1/chat/completions", fake_server.chat)
    app.router.add_post("/v1/embeddings", fake_server.embeddings)
    server = await aiohttp_server(app)
    return str(server.make_url("/v1"))


@pytest.fixture
def service(base_url: str) -> OpenAICompatibleService:
    return OpenAICompatibleService(
        base_url=base_url,
        generation_model="gemma-vision",
        embedding_model="nomic-embed-text",
    )


async def test_generate_text(
    service: OpenAICompatibleService, fake_server: FakeOpenAIServer
) -> None:
    assert await service.generate("Say hello") == "hello"
    assert fake_server.requests == [
        (
            "/v1/chat/completions",
            {"Authorization": ""},
            {
                "model": "gemma-vision",
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "Say hello"}]}
                ],
            },
        )
    ]


async def test_generate_with_image(
    service: OpenAICompatibleService, fake_server: FakeOpenAIServer
) -> None:
    await service.generate("Transcribe", image_png=b"png-bytes")

    _, _, payload = fake_server.requests[0]
    image_b64 = base64.b64encode(b"png-bytes").decode("ascii")
    assert payload["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Transcribe"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{image_b64}",
                        "detail": "high",
                    },
                },
            ],
        }
    ]


async def test_generate_with_json_schema_strips_code_fence(
    service: OpenAICompatibleService, fake_server: FakeOpenAIServer
) -> None:
    fake_server.chat_response = {
        "choices": [{"message": {"content": '```json\n{"segments": []}\n```'}}]
    }
    schema = {"type": "object", "properties": {"segments": {"type": "array"}}}

    assert await service.generate("Summarize", json_schema=schema) == (
        '{"segments": []}'
    )
    _, _, payload = fake_server.requests[0]
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "response", "schema": schema},
    }


async def test_generate_null_content(
    service: OpenAICompatibleService, fake_server: FakeOpenAIServer
) -> None:
    fake_server.chat_response = {"choices": [{"message": {"content": None}}]}
    assert await service.generate("Say hello") == ""


async def test_embed(
    service: OpenAICompatibleService, fake_server: FakeOpenAIServer
) -> None:
    assert await service.embed("some text") == [0.1, 0.2, 0.3]
    assert fake_server.requests == [
        (
            "/v1/embeddings",
            {"Authorization": ""},
            {"model": "nomic-embed-text", "input": "some text"},
        )
    ]


async def test_api_key_header(base_url: str, fake_server: FakeOpenAIServer) -> None:
    service = OpenAICompatibleService(
        base_url=base_url,
        generation_model="gpt",
        embedding_model="embed",
        api_key="secret",
    )
    await service.embed("text")
    _, headers, _ = fake_server.requests[0]
    assert headers == {"Authorization": "Bearer secret"}


async def test_separate_embedding_base_url(
    aiohttp_server: AiohttpServer, fake_server: FakeOpenAIServer
) -> None:
    embedding_server = FakeOpenAIServer(
        embedding_response={"data": [{"embedding": [1.0]}]}
    )
    app = web.Application()
    app.router.add_post("/v1/embeddings", embedding_server.embeddings)
    server = await aiohttp_server(app)

    service = OpenAICompatibleService(
        base_url="http://127.0.0.1:1/v1",
        generation_model="gpt",
        embedding_model="embed",
        embedding_base_url=str(server.make_url("/v1")),
    )
    assert await service.embed("text") == [1.0]
    assert len(embedding_server.requests) == 1


async def test_http_error_raises_llm_error(
    service: OpenAICompatibleService, fake_server: FakeOpenAIServer
) -> None:
    fake_server.status = 404
    with pytest.raises(LLMError, match="HTTP 404: model not found"):
        await service.generate("Say hello")


async def test_malformed_response_raises_llm_error(
    service: OpenAICompatibleService, fake_server: FakeOpenAIServer
) -> None:
    fake_server.embedding_response = {"data": []}
    with pytest.raises(LLMError, match="Unexpected embedding response"):
        await service.embed("text")


async def test_connection_error_raises_llm_error() -> None:
    service = OpenAICompatibleService(
        base_url="http://127.0.0.1:1/v1",
        generation_model="gpt",
        embedding_model="embed",
    )
    with pytest.raises(LLMError, match="request failed"):
        await service.generate("Say hello")


@pytest.mark.parametrize(
    ("base_url", "generation_model", "embedding_model"),
    [
        (None, "gpt", "embed"),
        ("http://localhost/v1", None, "embed"),
        ("http://localhost/v1", "gpt", None),
    ],
)
async def test_not_configured(
    base_url: str | None, generation_model: str | None, embedding_model: str | None
) -> None:
    service = OpenAICompatibleService(
        base_url=base_url,
        generation_model=generation_model,
        embedding_model=embedding_model,
    )
    assert not service.is_configured
    with pytest.raises(ValueError, match="not configured"):
        await service.generate("Say hello")


async def test_metrics(
    service: OpenAICompatibleService, fake_server: FakeOpenAIServer
) -> None:
    labels = {"operation": "embed_content", "status": "failure"}
    before = REGISTRY.get_sample_value("supernote_openai_api_calls_total", labels)

    fake_server.status = 500
    with pytest.raises(LLMError):
        await service.embed("text")

    after = REGISTRY.get_sample_value("supernote_openai_api_calls_total", labels)
    assert after == (before or 0.0) + 1.0
