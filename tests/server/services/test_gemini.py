from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import types

from supernote.server.services.gemini import GeminiService
from supernote.server.services.llm import LLMError


@pytest.fixture
def generate_content() -> AsyncMock:
    return AsyncMock(return_value=MagicMock(text="generated"))


@pytest.fixture
def embed_content() -> AsyncMock:
    return AsyncMock(return_value=MagicMock(embeddings=[MagicMock(values=[0.5, 0.25])]))


@pytest.fixture
def gemini(generate_content: AsyncMock, embed_content: AsyncMock) -> GeminiService:
    service = GeminiService(
        api_key="fake-key",
        generation_model="gemini-test",
        embedding_model="embedding-test",
    )
    client = MagicMock()
    client.aio.models.generate_content = generate_content
    client.aio.models.embed_content = embed_content
    service._client = client
    return service


def test_not_configured_without_api_key() -> None:
    service = GeminiService(
        api_key=None, generation_model="gemini-test", embedding_model="embed"
    )
    assert not service.is_configured
    assert service.generation_model == "gemini-test"


async def test_generate_text(
    gemini: GeminiService, generate_content: AsyncMock
) -> None:
    assert await gemini.generate("hello") == "generated"
    generate_content.assert_awaited_once_with(
        model="gemini-test", contents="hello", config=None
    )


async def test_generate_with_image(
    gemini: GeminiService, generate_content: AsyncMock
) -> None:
    await gemini.generate("Transcribe", image_png=b"png-bytes")

    kwargs = generate_content.call_args.kwargs
    (content,) = kwargs["contents"]
    assert content.parts[0].text == "Transcribe"
    assert content.parts[1].inline_data.data == b"png-bytes"
    assert content.parts[1].inline_data.mime_type == "image/png"
    assert kwargs["config"] == {
        "media_resolution": types.MediaResolution.MEDIA_RESOLUTION_HIGH
    }


async def test_generate_with_json_schema(
    gemini: GeminiService, generate_content: AsyncMock
) -> None:
    schema = {"type": "object"}
    await gemini.generate("Summarize", json_schema=schema)

    generate_content.assert_awaited_once_with(
        model="gemini-test",
        contents="Summarize",
        config={
            "response_mime_type": "application/json",
            "response_json_schema": schema,
        },
    )


async def test_generate_empty_response(
    gemini: GeminiService, generate_content: AsyncMock
) -> None:
    generate_content.return_value = MagicMock(text=None)
    assert await gemini.generate("hello") == ""


async def test_embed(gemini: GeminiService, embed_content: AsyncMock) -> None:
    assert await gemini.embed("some text") == [0.5, 0.25]
    embed_content.assert_awaited_once_with(model="embedding-test", contents="some text")


async def test_embed_missing_embeddings(
    gemini: GeminiService, embed_content: AsyncMock
) -> None:
    embed_content.return_value = MagicMock(embeddings=[])
    with pytest.raises(LLMError, match="No embeddings"):
        await gemini.embed("some text")
