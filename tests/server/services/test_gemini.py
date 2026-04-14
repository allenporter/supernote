import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from supernote.server.services.gemini import GeminiService


@pytest.fixture
def service() -> GeminiService:
    with patch("supernote.server.services.gemini.genai") as mock_genai:
        mock_genai.Client.return_value = MagicMock()
        svc = GeminiService(
            api_key="fake-key",
            ocr_model="gemini-ocr-model",
            embedding_model="gemini-embedding-001",
            chat_model="gemini-2.0-flash",
            max_concurrency=2,
        )
    return svc


def test_is_configured_with_key() -> None:
    with patch("supernote.server.services.gemini.genai"):
        svc = GeminiService(
            api_key="key", ocr_model="m", embedding_model="m", chat_model="m"
        )
    assert svc.is_configured


def test_is_configured_without_key() -> None:
    svc = GeminiService(
        api_key=None, ocr_model="m", embedding_model="m", chat_model="m"
    )
    assert not svc.is_configured


def test_provider_name(service: GeminiService) -> None:
    assert service.provider_name == "GEMINI"


def test_max_concurrency_clamped_to_one() -> None:
    with patch("supernote.server.services.gemini.genai"):
        svc = GeminiService(
            api_key="key",
            ocr_model="m",
            embedding_model="m",
            chat_model="m",
            max_concurrency=0,
        )
    assert svc.max_concurrency == 1


async def test_ocr_image(service: GeminiService) -> None:
    mock_response = MagicMock()
    mock_response.text = "OCR text output"
    service._client.aio.models.generate_content = AsyncMock(return_value=mock_response)  # type: ignore[union-attr, method-assign]

    result = await service.ocr_image(b"png-bytes", prompt="Extract text")

    assert result == "OCR text output"
    call_kwargs = service._client.aio.models.generate_content.call_args.kwargs  # type: ignore[union-attr]
    assert call_kwargs["model"] == "gemini-ocr-model"


async def test_ocr_image_empty_text(service: GeminiService) -> None:
    mock_response = MagicMock()
    mock_response.text = None
    service._client.aio.models.generate_content = AsyncMock(return_value=mock_response)  # type: ignore[union-attr, method-assign]

    result = await service.ocr_image(b"png-bytes", prompt="Extract text")

    assert result == ""


async def test_ocr_image_not_configured() -> None:
    svc = GeminiService(
        api_key=None, ocr_model="m", embedding_model="m", chat_model="m"
    )
    with pytest.raises(ValueError, match="not configured"):
        await svc.ocr_image(b"data", prompt="")


async def test_embed_text(service: GeminiService) -> None:
    mock_embedding = MagicMock()
    mock_embedding.values = [0.1, 0.2, 0.3]
    mock_response = MagicMock()
    mock_response.embeddings = [mock_embedding]
    service._client.aio.models.embed_content = AsyncMock(return_value=mock_response)  # type: ignore[union-attr, method-assign]

    result = await service.embed_text("hello")

    assert result == [0.1, 0.2, 0.3]
    service._client.aio.models.embed_content.assert_called_once_with(  # type: ignore[union-attr]
        model="gemini-embedding-001",
        contents="hello",
        config=None,
    )


async def test_embed_text_no_embeddings(service: GeminiService) -> None:
    mock_response = MagicMock()
    mock_response.embeddings = []
    service._client.aio.models.embed_content = AsyncMock(return_value=mock_response)  # type: ignore[union-attr, method-assign]

    with pytest.raises(ValueError, match="No embeddings"):
        await service.embed_text("hello")


async def test_embed_text_empty_values(service: GeminiService) -> None:
    mock_embedding = MagicMock()
    mock_embedding.values = []
    mock_response = MagicMock()
    mock_response.embeddings = [mock_embedding]
    service._client.aio.models.embed_content = AsyncMock(return_value=mock_response)  # type: ignore[union-attr, method-assign]

    with pytest.raises(ValueError, match="Empty embedding values"):
        await service.embed_text("hello")


async def test_embed_text_not_configured() -> None:
    svc = GeminiService(
        api_key=None, ocr_model="m", embedding_model="m", chat_model="m"
    )
    with pytest.raises(ValueError, match="not configured"):
        await svc.embed_text("hello")


async def test_generate_json(service: GeminiService) -> None:
    mock_response = MagicMock()
    mock_response.text = '{"result": "ok"}'
    service._client.aio.models.generate_content = AsyncMock(return_value=mock_response)  # type: ignore[union-attr, method-assign]

    result = await service.generate_json("Summarise this", schema={"type": "object"})

    assert result == '{"result": "ok"}'
    call_kwargs = service._client.aio.models.generate_content.call_args.kwargs  # type: ignore[union-attr]
    assert call_kwargs["model"] == "gemini-2.0-flash"


async def test_generate_json_empty_response(service: GeminiService) -> None:
    mock_response = MagicMock()
    mock_response.text = None
    service._client.aio.models.generate_content = AsyncMock(return_value=mock_response)  # type: ignore[union-attr, method-assign]

    result = await service.generate_json("prompt", schema={})

    assert result == ""


async def test_generate_json_not_configured() -> None:
    svc = GeminiService(
        api_key=None, ocr_model="m", embedding_model="m", chat_model="m"
    )
    with pytest.raises(ValueError, match="not configured"):
        await svc.generate_json("prompt", schema={})


async def test_concurrency_limit() -> None:
    max_concurrency = 2

    with patch("supernote.server.services.gemini.genai") as mock_genai:
        mock_genai.Client.return_value = MagicMock()
        service = GeminiService(
            api_key="fake-key",
            ocr_model="m",
            embedding_model="gemini-embedding-001",
            chat_model="m",
            max_concurrency=max_concurrency,
        )

    active_calls = 0
    max_active_seen = 0

    async def slow_embed(*args: object, **kwargs: object) -> MagicMock:
        nonlocal active_calls, max_active_seen
        active_calls += 1
        max_active_seen = max(max_active_seen, active_calls)
        try:
            await asyncio.sleep(0.05)
            mock_embedding = MagicMock()
            mock_embedding.values = [0.1]
            mock_response = MagicMock()
            mock_response.embeddings = [mock_embedding]
            return mock_response
        finally:
            active_calls -= 1

    service._client.aio.models.embed_content = AsyncMock(side_effect=slow_embed)  # type: ignore[union-attr, method-assign]

    tasks = [service.embed_text("text") for _ in range(5)]
    await asyncio.gather(*tasks)

    assert max_active_seen == max_concurrency
    assert active_calls == 0
