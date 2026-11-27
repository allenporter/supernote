"""Tests for `supernote.server.components.gemini.ocr`."""

from __future__ import annotations

import base64

from supernote.server.ai.models.ocr import OcrModel
from supernote.server.ai.prompts import PageMetadata, format_ocr_prompt
from supernote.server.config import ModelConfig, ProviderConfig

from .conftest import FakeGeminiServer, LoadGeminiModels


async def test_gemini_ocr_model(
    gemini_ocr_model: OcrModel,
    fake_gemini: FakeGeminiServer,
) -> None:
    page_meta = PageMetadata(
        file_name="real.note",
        page_index=0,
        page_id="p0",
        notebook_create_time=None,
    )
    ocr_prompt = format_ocr_prompt(page_meta)
    ocr_result = await gemini_ocr_model.extract_text(b"fake-png-data", ocr_prompt)
    assert ocr_result == "Handwritten text content"
    assert gemini_ocr_model.model_id == "gemini-2.0-flash-exp"

    assert len(fake_gemini.requests) == 1
    path, api_key, payload = fake_gemini.requests[0]
    assert path == "/v1beta/models/gemini-2.0-flash-exp:generateContent"
    assert api_key == "test-key"
    parts = payload["contents"][0]["parts"]
    assert len(parts) == 2
    assert parts[0]["text"] == ocr_prompt
    assert "Notebook Filename: real.note" in parts[0]["text"]
    assert parts[1]["inlineData"] == {
        "data": base64.b64encode(b"fake-png-data")
        .decode("ascii")
        .replace("+", "-")
        .replace("/", "_"),
        "mime_type": "image/png",
    }
    assert payload["generationConfig"] == {"mediaResolution": "MEDIA_RESOLUTION_HIGH"}


async def test_gemini_ocr_named_provider(
    load_gemini_models: LoadGeminiModels,
    fake_gemini: FakeGeminiServer,
    gemini_base_url: str,
) -> None:
    ocr, _, _ = await load_gemini_models(
        providers={
            "work": ProviderConfig(
                type="gemini", api_key="work-key", base_url=gemini_base_url
            )
        },
        ocr=ModelConfig(provider="work", model="gemini-custom"),
    )
    assert ocr is not None
    assert ocr.provider == "work"
    assert ocr.model_id == "gemini-custom"
    assert await ocr.extract_text(b"png", "prompt") == "Handwritten text content"
    assert fake_gemini.requests[0][1] == "work-key"
