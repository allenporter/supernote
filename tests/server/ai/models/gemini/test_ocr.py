"""Tests for `supernote.server.ai.models.gemini.ocr`."""

from __future__ import annotations

import base64

from supernote.server.ai.models.gemini.backend import GeminiBackend
from supernote.server.ai.models.gemini.ocr import GeminiOcrModel, create_ocr_model
from supernote.server.ai.prompts import PageMetadata, format_ocr_prompt
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig, ServerConfig

from .conftest import FakeGeminiServer


async def test_gemini_ocr_model(
    gemini_backend: GeminiBackend,
    fake_gemini: FakeGeminiServer,
) -> None:
    ocr_model = GeminiOcrModel(gemini_backend, "gemini-2.0-flash-exp")

    page_meta = PageMetadata(
        file_name="real.note",
        page_index=0,
        page_id="p0",
        notebook_create_time=None,
    )
    ocr_prompt = format_ocr_prompt(page_meta)
    ocr_result = await ocr_model.extract_text(b"fake-png-data", ocr_prompt)
    assert ocr_result == "Handwritten text content"
    assert ocr_model.model_id == "gemini-2.0-flash-exp"

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


def test_create_ocr_model() -> None:
    assert create_ocr_model(ServerConfig()) is None

    config = ServerConfig(
        ai=AiConfig(
            providers={"work": ProviderConfig(type="gemini", api_key="work-key")},
            ocr=ModelConfig(provider="work", model="gemini-custom"),
        )
    )
    model = create_ocr_model(config)
    assert isinstance(model, GeminiOcrModel)
    assert model.model_id == "gemini-custom"
