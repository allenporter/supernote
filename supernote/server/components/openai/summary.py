"""OpenAI-compatible structured notebook summarization model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from supernote.server.ai.models.summary import SummaryModel
from supernote.server.ai.prompts import (
    SummaryResponse,
    get_summary_json_schema,
    parse_summary_response,
)

from . import resolve_openai_backend
from .backend import OpenAIBackend

if TYPE_CHECKING:
    from supernote.server.components.ai import AiRegistrar
    from supernote.server.core import ServerCore

__all__ = [
    "OpenAISummaryModel",
    "async_setup_summary",
]


class OpenAISummaryModel(SummaryModel):
    """OpenAI-compatible structured notebook summarization model."""

    def __init__(self, backend: OpenAIBackend, model_name: str) -> None:
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
        text = await self._backend.chat_completion(
            model=self._model_name,
            content=[{"type": "text", "text": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "summary_response",
                    "schema": get_summary_json_schema(),
                },
            },
        )
        return parse_summary_response(text)


async def async_setup_summary(core: ServerCore, registrar: AiRegistrar) -> None:
    """Register the ``openai`` summary provider with `AiRegistrar`."""

    def _create(provider: str, model: str) -> SummaryModel | None:
        backend = resolve_openai_backend(core, provider)
        return OpenAISummaryModel(backend, model) if backend is not None else None

    registrar.register_summary("openai", _create)
