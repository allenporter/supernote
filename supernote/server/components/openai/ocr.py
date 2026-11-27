"""OpenAI-compatible page OCR model."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from supernote.server.ai.models.ocr import OcrModel

from . import resolve_openai_backend
from .backend import OpenAIBackend

if TYPE_CHECKING:
    from supernote.server.components.ai import AiRegistrar
    from supernote.server.core import ServerCore

__all__ = [
    "OpenAIOcrModel",
    "async_setup_ocr",
]


class OpenAIOcrModel(OcrModel):
    """OpenAI-compatible page OCR model using a vision-capable chat model."""

    def __init__(self, backend: OpenAIBackend, model_name: str) -> None:
        self._backend = backend
        self._model_name = model_name

    @property
    def provider(self) -> str:
        return self._backend.provider

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


async def async_setup_ocr(core: ServerCore, registrar: AiRegistrar) -> None:
    """Register the ``openai`` OCR provider with `AiRegistrar`."""

    def _create(provider: str, model: str) -> OcrModel | None:
        backend = resolve_openai_backend(core, provider)
        return OpenAIOcrModel(backend, model) if backend is not None else None

    registrar.register_ocr("openai", _create)
