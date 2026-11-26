"""Configuration model for the AI capability host component (`AiComponentConfig`)."""

from __future__ import annotations

from dataclasses import dataclass, field

from mashumaro.config import TO_DICT_ADD_OMIT_NONE_FLAG, BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from supernote.server.config import ModelConfig, ProviderConfig


@dataclass
class AiComponentConfig(DataClassJSONMixin):
    """Per-component settings for `supernote.server.components.ai`."""

    enabled: bool = True
    """Whether the AI capability registry and platform host are enabled."""

    prompts_dir: str | None = None
    """Optional directory containing custom AI prompt templates."""

    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    """Configured AI providers keyed by provider name."""

    ocr: ModelConfig | None = None
    """Model configuration for page OCR extraction."""

    summary: ModelConfig | None = None
    """Model configuration for notebook summary generation."""

    embedding: ModelConfig | None = None
    """Model configuration for page embedding generation."""

    text: ModelConfig | None = None
    """Optional model configuration for structured JSON text generation (falls back to `summary` when unset)."""

    @property
    def effective_text(self) -> ModelConfig | None:
        """Return `text` model configuration, falling back to `summary` when unset."""
        return self.text if self.text is not None else self.summary

    def provider_type(self, name: str) -> str:
        """Return the backend implementation for the `providers` entry `name`."""
        provider_cfg = self.providers.get(name)
        if provider_cfg is not None and provider_cfg.type:
            return provider_cfg.type
        return name

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]
