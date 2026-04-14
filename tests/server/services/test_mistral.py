import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from supernote.server.services.mistral import MistralService


@pytest.fixture
def service() -> MistralService:
    with patch("supernote.server.services.mistral.Mistral"):
        return MistralService(
            api_key="fake-key",
            ocr_model="mistral-ocr-latest",
            embedding_model="mistral-embed",
            chat_model="mistral-large-latest",
            max_concurrency=2,
        )


def test_is_configured_with_key() -> None:
    with patch("supernote.server.services.mistral.Mistral"):
        svc = MistralService(
            api_key="key",
            ocr_model="m",
            embedding_model="m",
            chat_model="m",
        )
    assert svc.is_configured


def test_is_configured_without_key() -> None:
    svc = MistralService(
        api_key=None,
        ocr_model="m",
        embedding_model="m",
        chat_model="m",
    )
    assert not svc.is_configured


def test_provider_name(service: MistralService) -> None:
    assert service.provider_name == "MISTRAL"


async def test_ocr_image(service: MistralService) -> None:
    mock_page = MagicMock()
    mock_page.markdown = "Extracted text"
    mock_response = MagicMock()
    mock_response.pages = [mock_page]
    service._client.ocr.process_async = AsyncMock(return_value=mock_response)  # type: ignore[union-attr, method-assign]

    result = await service.ocr_image(b"png-bytes", prompt="ignored")

    assert result == "Extracted text"
    call_kwargs = service._client.ocr.process_async.call_args.kwargs  # type: ignore[union-attr]
    assert call_kwargs["model"] == "mistral-ocr-latest"
    assert call_kwargs["document"]["type"] == "image_url"
    assert call_kwargs["document"]["image_url"].startswith("data:image/png;base64,")


async def test_ocr_image_multiple_pages(service: MistralService) -> None:
    pages = [MagicMock(markdown=f"Page {i}") for i in range(3)]
    mock_response = MagicMock()
    mock_response.pages = pages
    service._client.ocr.process_async = AsyncMock(return_value=mock_response)  # type: ignore[union-attr, method-assign]

    result = await service.ocr_image(b"png-bytes", prompt="")

    assert result == "Page 0\n\nPage 1\n\nPage 2"


async def test_ocr_image_not_configured() -> None:
    svc = MistralService(
        api_key=None, ocr_model="m", embedding_model="m", chat_model="m"
    )
    with pytest.raises(ValueError, match="not configured"):
        await svc.ocr_image(b"data", prompt="")


async def test_embed_text(service: MistralService) -> None:
    mock_embedding = MagicMock()
    mock_embedding.embedding = [0.1, 0.2, 0.3]
    mock_response = MagicMock()
    mock_response.data = [mock_embedding]
    service._client.embeddings.create_async = AsyncMock(return_value=mock_response)  # type: ignore[union-attr, method-assign]

    result = await service.embed_text("hello")

    assert result == [0.1, 0.2, 0.3]
    service._client.embeddings.create_async.assert_called_once_with(  # type: ignore[union-attr]
        model="mistral-embed",
        inputs=["hello"],
    )


async def test_embed_text_empty_response(service: MistralService) -> None:
    mock_response = MagicMock()
    mock_response.data = []
    service._client.embeddings.create_async = AsyncMock(return_value=mock_response)  # type: ignore[union-attr, method-assign]

    with pytest.raises(ValueError, match="No embeddings"):
        await service.embed_text("hello")


async def test_embed_text_not_configured() -> None:
    svc = MistralService(
        api_key=None, ocr_model="m", embedding_model="m", chat_model="m"
    )
    with pytest.raises(ValueError, match="not configured"):
        await svc.embed_text("hello")


async def test_generate_json(service: MistralService) -> None:
    mock_choice = MagicMock()
    mock_choice.message.content = '{"result": "ok"}'
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    service._client.chat.complete_async = AsyncMock(return_value=mock_response)  # type: ignore[union-attr, method-assign]

    result = await service.generate_json("Summarise this", schema={"type": "object"})

    assert result == '{"result": "ok"}'


async def test_generate_json_not_configured() -> None:
    svc = MistralService(
        api_key=None, ocr_model="m", embedding_model="m", chat_model="m"
    )
    with pytest.raises(ValueError, match="not configured"):
        await svc.generate_json("prompt", schema={})


async def test_ocr_image_empty_pages(service: MistralService) -> None:
    mock_response = MagicMock()
    mock_response.pages = []
    service._client.ocr.process_async = AsyncMock(return_value=mock_response)  # type: ignore[union-attr, method-assign]

    result = await service.ocr_image(b"png-bytes", prompt="")

    assert result == ""


async def test_ocr_image_missing_pages(service: MistralService) -> None:
    mock_response = MagicMock(spec=[])  # no 'pages' attribute
    service._client.ocr.process_async = AsyncMock(return_value=mock_response)  # type: ignore[union-attr, method-assign]

    result = await service.ocr_image(b"png-bytes", prompt="")

    assert result == ""


async def test_ocr_image_skips_pages_without_markdown(service: MistralService) -> None:
    page_with_text = MagicMock()
    page_with_text.markdown = "Real text"
    page_no_markdown = MagicMock(spec=[])  # no 'markdown' attribute
    mock_response = MagicMock()
    mock_response.pages = [page_with_text, page_no_markdown]
    service._client.ocr.process_async = AsyncMock(return_value=mock_response)  # type: ignore[union-attr, method-assign]

    result = await service.ocr_image(b"png-bytes", prompt="")

    assert result == "Real text"


async def test_generate_json_non_string_content(service: MistralService) -> None:
    import json

    mock_choice = MagicMock()
    mock_choice.message.content = {"result": "ok"}  # dict, not str
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    service._client.chat.complete_async = AsyncMock(return_value=mock_response)  # type: ignore[union-attr, method-assign]

    result = await service.generate_json("prompt", schema={})

    parsed = json.loads(result)
    assert parsed == {"result": "ok"}


async def test_generate_json_empty_choices(service: MistralService) -> None:
    mock_response = MagicMock()
    mock_response.choices = []
    service._client.chat.complete_async = AsyncMock(return_value=mock_response)  # type: ignore[union-attr, method-assign]

    result = await service.generate_json("prompt", schema={})

    assert result == ""


def test_max_concurrency_clamped_to_one() -> None:
    with patch("supernote.server.services.mistral.Mistral"):
        svc = MistralService(
            api_key="key",
            ocr_model="m",
            embedding_model="m",
            chat_model="m",
            max_concurrency=0,
        )
    assert svc.max_concurrency == 1


async def test_concurrency_limit() -> None:
    max_concurrency = 2

    with patch("supernote.server.services.mistral.Mistral"):
        service = MistralService(
            api_key="fake-key",
            ocr_model="mistral-ocr-latest",
            embedding_model="mistral-embed",
            chat_model="mistral-large-latest",
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
            mock_data = MagicMock()
            mock_data.embedding = [0.1]
            mock_response = MagicMock()
            mock_response.data = [mock_data]
            return mock_response
        finally:
            active_calls -= 1

    service._client.embeddings.create_async = AsyncMock(side_effect=slow_embed)  # type: ignore[union-attr, method-assign]

    tasks = [service.embed_text("text") for _ in range(5)]
    await asyncio.gather(*tasks)

    assert max_active_seen == max_concurrency
    assert active_calls == 0
