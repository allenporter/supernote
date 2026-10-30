"""OpenAI-compatible structured notebook summarization model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from supernote.server.ai.models.summary import SummaryModel
from supernote.server.ai.prompts import (
    SummaryResponse,
    get_summary_json_schema,
    parse_summary_response,
)

from .backend import OpenAIBackend, create_openai_backend

if TYPE_CHECKING:
    from supernote.server.config import ServerConfig

__all__ = [
    "OpenAISummaryModel",
    "create_summary_model",
]


class OpenAISummaryModel(SummaryModel):
    """OpenAI-compatible structured notebook summarization model."""

    def __init__(self, backend: OpenAIBackend, model_name: str) -> None:
        self._backend = backend
        self._model_name = model_name

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


def create_summary_model(config: ServerConfig) -> SummaryModel | None:
    """Create an `OpenAISummaryModel` from `ServerConfig`, or `None` if unconfigured."""
    model_cfg = config.ai.summary
    if model_cfg is None:
        return None
    backend = create_openai_backend(config.ai.providers, model_cfg.provider)
    if backend is None:
        return None
    return OpenAISummaryModel(backend, model_cfg.model)
