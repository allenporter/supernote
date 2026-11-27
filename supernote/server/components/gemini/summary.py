"""Gemini-backed structured notebook summarization model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.genai import types

from supernote.server.ai.models.summary import SummaryModel
from supernote.server.ai.prompts import (
    SummaryResponse,
    get_summary_json_schema,
    parse_summary_response,
)

from . import resolve_gemini_backend
from .backend import GeminiBackend

if TYPE_CHECKING:
    from supernote.server.components.ai import AiRegistrar
    from supernote.server.core import ServerCore

__all__ = [
    "GeminiSummaryModel",
    "async_setup_summary",
]


class GeminiSummaryModel(SummaryModel):
    """Gemini-backed structured notebook summarization model."""

    def __init__(self, backend: GeminiBackend, model_name: str) -> None:
        self._backend = backend
        self._model_name = model_name

    @property
    def provider(self) -> str:
        return self._backend.provider

    @property
    def model_id(self) -> str:
        return self._model_name

    async def summarize(
        self,
        prompt: str,
    ) -> SummaryResponse:
        response = await self._backend.generate_content(
            model=self._model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=get_summary_json_schema(),
            ),
        )
        return parse_summary_response(response.text)


async def async_setup_summary(core: ServerCore, registrar: AiRegistrar) -> None:
    """Register the ``gemini`` summary provider with `AiRegistrar`."""

    def _create(provider: str, model: str) -> SummaryModel | None:
        backend = resolve_gemini_backend(core, provider)
        return GeminiSummaryModel(backend, model) if backend is not None else None

    registrar.register_summary("gemini", _create)
