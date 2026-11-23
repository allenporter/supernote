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

from .backend import GeminiBackend, create_gemini_backend

if TYPE_CHECKING:
    from supernote.server.components.ai import AiRegistrar
    from supernote.server.config import ServerConfig
    from supernote.server.core import ServerCore

__all__ = [
    "GeminiSummaryModel",
    "async_setup_summary",
    "create_summary_model",
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


def create_summary_model(config: ServerConfig) -> SummaryModel | None:
    """Create a `GeminiSummaryModel` from `ServerConfig`, or `None` if unconfigured."""
    model_cfg = config.ai.summary
    if model_cfg is None:
        return None
    backend = create_gemini_backend(config.ai.providers, model_cfg.provider)
    if backend is None:
        return None
    return GeminiSummaryModel(backend, model_cfg.model)


async def async_setup_summary(core: ServerCore, registrar: AiRegistrar) -> None:
    """Register the ``gemini`` summary provider with `AiRegistrar`."""
    registrar.register_summary("gemini", create_summary_model)
