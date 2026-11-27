"""Tests for `supernote.server.components.openai.ocr`."""

from __future__ import annotations

import base64

from supernote.server.ai.models.ocr import OcrModel

from .conftest import FakeOpenAIServer


async def test_openai_ocr_model(
    openai_ocr_model: OcrModel, fake_openai: FakeOpenAIServer
) -> None:
    text = await openai_ocr_model.extract_text(b"png-bytes", "Transcribe this page.")

    assert openai_ocr_model.provider == "openai"
    assert openai_ocr_model.model_id == "gemma-vision"
    assert text == "transcribed text"
    image_b64 = base64.b64encode(b"png-bytes").decode("ascii")
    assert fake_openai.requests == [
        (
            "/v1/chat/completions",
            "",
            {
                "model": "gemma-vision",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Transcribe this page."},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_b64}",
                                    "detail": "high",
                                },
                            },
                        ],
                    }
                ],
            },
        )
    ]
