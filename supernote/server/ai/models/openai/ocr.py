"""OpenAI-compatible page OCR model."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from supernote.server.ai.models.ocr import OcrModel

from .backend import OpenAIBackend, create_openai_backend

if TYPE_CHECKING:
    from supernote.server.config import ServerConfig

__all__ = [
    "OpenAIOcrModel",
    "create_ocr_model",
]


class OpenAIOcrModel(OcrModel):
    """OpenAI-compatible page OCR model using a vision-capable chat model."""

    def __init__(self, backend: OpenAIBackend, model_name: str) -> None:
        self._backend = backend
        self._model_name = model_name

    @property
    def model_id(self) -> str:
        return self._model_name

    async def extract_text(
        self,
        png_data: bytes,
        prompt: str,
    ) -> str:
        image_b64 = base64.b64encode(png_data).decode("ascii")
        return await self._backend.chat_completion(
            model=self._model_name,
            content=[
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{image_b64}",
                        "detail": "high",
                    },
                },
            ],
        )


def create_ocr_model(config: ServerConfig) -> OcrModel | None:
    """Create an `OpenAIOcrModel` from `ServerConfig`, or `None` if unconfigured."""
    model_cfg = config.ai.ocr
    backend = create_openai_backend(config.ai.providers)
    if model_cfg is None or backend is None:
        return None
    return OpenAIOcrModel(backend, model_cfg.model)
