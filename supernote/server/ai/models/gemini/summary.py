"""Gemini-backed structured notebook summarization model."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from google.genai import types

from supernote.server.ai.base import AIError
from supernote.server.ai.models.summary import SummaryModel
from supernote.server.ai.prompts import SummaryResponse, get_summary_json_schema

from .backend import GeminiBackend

if TYPE_CHECKING:
    from supernote.server.config import ServerConfig

__all__ = [
    "GeminiSummaryModel",
    "create_summary_model",
]


class GeminiSummaryModel(SummaryModel):
    """Gemini-backed structured notebook summarization model."""

    def __init__(self, backend: GeminiBackend, model_name: str) -> None:
        self._backend = backend
        self._model_name = model_name

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
        if not response.text:
            return SummaryResponse(segments=[])
        try:
            data = json.loads(response.text)
            return SummaryResponse.from_dict(data)
        except (ValueError, TypeError, KeyError) as err:
            raise AIError(
                f"Failed to parse Gemini summary JSON response: {err}"
            ) from err


def create_summary_model(config: ServerConfig) -> SummaryModel | None:
    """Create a `GeminiSummaryModel` from `ServerConfig`, or `None` if unconfigured."""
    api_key = config.gemini_api_key
    if not api_key or not api_key.strip():
        return None
    return GeminiSummaryModel(GeminiBackend(api_key), config.gemini_ocr_model)
