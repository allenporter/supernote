"""OpenAI-compatible structured notebook summarization model."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from supernote.server.ai.base import AIError
from supernote.server.ai.models.summary import SummaryModel
from supernote.server.ai.prompts import SummaryResponse, get_summary_json_schema

from .backend import OpenAIBackend, create_openai_backend

if TYPE_CHECKING:
    from supernote.server.config import ServerConfig

__all__ = [
    "OpenAISummaryModel",
    "create_summary_model",
]

_CODE_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n?```\s*$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    """Remove a Markdown code fence that some local models wrap JSON output in."""
    match = _CODE_FENCE.match(text.strip())
    return match.group(1) if match else text


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
        if not text.strip():
            return SummaryResponse(segments=[])
        try:
            data = json.loads(_strip_code_fence(text))
            return SummaryResponse.from_dict(data)
        except (ValueError, TypeError, KeyError) as err:
            raise AIError(
                f"Failed to parse OpenAI-compatible summary JSON response: {err}"
            ) from err


def create_summary_model(config: ServerConfig) -> SummaryModel | None:
    """Create an `OpenAISummaryModel` from `ServerConfig`, or `None` if unconfigured."""
    model_cfg = config.ai.summary
    backend = create_openai_backend(config.ai.providers)
    if model_cfg is None or backend is None:
        return None
    return OpenAISummaryModel(backend, model_cfg.model)
