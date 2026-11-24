"""Fake structured JSON text generation model for testing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from supernote.server.ai.models.text import TextGenerationModel
from supernote.server.metrics import AIStage

if TYPE_CHECKING:
    from supernote.server.components.ai import AiRegistrar
    from supernote.server.config import ServerConfig
    from supernote.server.core import ServerCore

__all__ = [
    "FakeTextGenerationModel",
    "async_setup_text",
    "create_text_model",
]


class FakeTextGenerationModel(TextGenerationModel):
    """Deterministic fake `TextGenerationModel` returning configured JSON dicts."""

    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        model_id: str = "fake-text-v1",
        error: Exception | None = None,
        provider: str = "fake",
    ) -> None:
        self._responses = list(responses) if responses is not None else None
        self._model_id = model_id
        self.error = error
        self._provider = provider
        self.calls: list[dict[str, Any]] = []

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model_id(self) -> str:
        return self._model_id

    async def generate_json(
        self,
        prompt: str,
        *,
        response_schema: Mapping[str, Any],
        schema_name: str = "structured_response",
        stage: AIStage = AIStage.TEXT,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "prompt": prompt,
                "response_schema": dict(response_schema),
                "schema_name": schema_name,
                "stage": stage,
            }
        )
        if self.error is not None:
            raise self.error
        if self._responses is not None and self._responses:
            return dict(self._responses.pop(0))
        return {"page_ops": [], "log_entry": f"Compiled ({len(prompt)} chars)"}


def create_text_model(config: ServerConfig) -> TextGenerationModel | None:
    """Create a `FakeTextGenerationModel` from `ServerConfig`, or `None` if unconfigured."""
    if config.ai.text is None:
        return None
    return FakeTextGenerationModel(
        model_id=config.ai.text.model,
        provider=config.ai.text.provider,
    )


async def async_setup_text(core: ServerCore, registrar: AiRegistrar) -> None:
    """Register the ``fake`` text generation provider with `AiRegistrar`."""
    registrar.register_text("fake", create_text_model)
