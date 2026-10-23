"""Tests for `supernote.server.ai.models.openai.ocr`."""

from __future__ import annotations

import base64

from supernote.server.ai.models.openai.backend import OpenAIBackend
from supernote.server.ai.models.openai.ocr import OpenAIOcrModel, create_ocr_model
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig, ServerConfig

from .conftest import FakeOpenAIServer


async def test_openai_ocr_model(
    openai_backend: OpenAIBackend, fake_openai: FakeOpenAIServer
) -> None:
    model = OpenAIOcrModel(openai_backend, "gemma-vision")

    text = await model.extract_text(b"png-bytes", "Transcribe this page.")

    assert model.model_id == "gemma-vision"
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


def test_create_ocr_model() -> None:
    assert create_ocr_model(ServerConfig()) is None

    config = ServerConfig(
        ai=AiConfig(
            providers={"openai": ProviderConfig(base_url="http://localhost/v1")},
            ocr=ModelConfig(provider="openai", model="gemma-vision"),
        )
    )
    model = create_ocr_model(config)
    assert isinstance(model, OpenAIOcrModel)
    assert model.model_id == "gemma-vision"
