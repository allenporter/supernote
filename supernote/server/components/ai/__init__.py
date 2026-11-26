"""AI model registry and platform host (`AiComponent` and `AiRegistrar`).

Manages the AI model backends used for notebook OCR, summarization, and
semantic search embeddings. Rather than hardcoding vendors like Gemini, OpenAI,
or Apple Vision in one place, each backend registers its supported capabilities
here during server startup, and this component wraps every model with shared
Prometheus metrics, concurrency limiting, and embedding vector validation.

Provides `AiComponent`, `AI_PLATFORMS` (``("ocr", "summary", "embedding")``),
and `AiRegistrar` (passed into
``<component>.<platform>:async_setup_<platform>(core, registrar)``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from aiohttp import web

from supernote.server.ai.models.embedding import (
    ConcurrencyLimitedEmbeddingModel,
    EmbeddingModel,
    InstrumentedEmbeddingModel,
    ValidatingEmbeddingModel,
)
from supernote.server.ai.models.ocr import (
    ConcurrencyLimitedOcrModel,
    InstrumentedOcrModel,
    OcrModel,
    PromptOverrideOcrModel,
)
from supernote.server.ai.models.summary import (
    ConcurrencyLimitedSummaryModel,
    InstrumentedSummaryModel,
    SummaryModel,
)
from supernote.server.ai.models.text import (
    ConcurrencyLimitedTextGenerationModel,
    InstrumentedTextGenerationModel,
    TextGenerationModel,
)
from supernote.server.core import ServerCore
from supernote.server.utils.prompt_loader import PROMPT_LOADER

from .config import AiComponentConfig

if TYPE_CHECKING:
    from supernote.server.config import ModelConfig

__all__ = [
    "AI_PLATFORMS",
    "EMBEDDING_MODEL_KEY",
    "OCR_MODEL_KEY",
    "SUMMARY_MODEL_KEY",
    "TEXT_MODEL_KEY",
    "AiComponent",
    "AiRegistrar",
]

AI_PLATFORMS: tuple[str, ...] = ("ocr", "summary", "embedding", "text")
"""AI capability platform names hosted by `AiComponent`."""

OCR_MODEL_KEY: web.AppKey[OcrModel | None] = web.AppKey("ocr_model")
"""Typed `AppKey` for the configured OCR model; read by components declaring ``dependencies = ("ai",)``."""

SUMMARY_MODEL_KEY: web.AppKey[SummaryModel | None] = web.AppKey("summary_model")
"""Typed `AppKey` for the configured summary model; read by components declaring ``dependencies = ("ai",)``."""

EMBEDDING_MODEL_KEY: web.AppKey[EmbeddingModel | None] = web.AppKey("embedding_model")
"""Typed `AppKey` for the configured embedding model; read by components declaring ``dependencies = ("ai",)``."""

TEXT_MODEL_KEY: web.AppKey[TextGenerationModel | None] = web.AppKey("text_model")
"""Typed `AppKey` for the configured structured text-generation model; read by components declaring ``dependencies = ("ai",)``."""

_ModelT = TypeVar("_ModelT")
OcrModelFactory = Callable[[str, str], OcrModel | None]
SummaryModelFactory = Callable[[str, str], SummaryModel | None]
EmbeddingModelFactory = Callable[[str, str], EmbeddingModel | None]
TextModelFactory = Callable[[str, str], TextGenerationModel | None]


def _normalize_provider_type(provider_type: str) -> str:
    normalized = provider_type.strip().lower()
    if not normalized:
        raise ValueError("AI provider type must be non-empty")
    return normalized


def _register_factory(
    registry: dict[str, Callable[[str, str], _ModelT | None]],
    capability: str,
    provider_type: str,
    factory: Callable[[str, str], _ModelT | None],
) -> None:
    key = _normalize_provider_type(provider_type)
    if key in registry:
        raise ValueError(f"{capability} provider {key!r} is already registered")
    registry[key] = factory


def _instantiate_raw_model(
    registry: Mapping[str, Callable[[str, str], _ModelT | None]],
    capability: str,
    config: AiComponentConfig,
    model_cfg: ModelConfig | None,
) -> tuple[_ModelT, ModelConfig] | None:
    if model_cfg is None:
        return None
    raw_provider_type = config.provider_type(model_cfg.provider)
    key = raw_provider_type.strip().lower()
    factory = registry.get(key)
    if factory is None:
        raise ValueError(
            f"Unsupported {capability} model provider type: {raw_provider_type!r}"
        )
    model = factory(model_cfg.provider, model_cfg.model)
    if model is None:
        return None
    return model, model_cfg


class AiRegistrar:
    """Registrar passed into ``<component>.{ocr,summary,embedding}:async_setup_*``."""

    def __init__(self) -> None:
        self._ocr_factories: dict[str, OcrModelFactory] = {}
        self._summary_factories: dict[str, SummaryModelFactory] = {}
        self._embedding_factories: dict[str, EmbeddingModelFactory] = {}
        self._text_factories: dict[str, TextModelFactory] = {}

    @property
    def platforms(self) -> tuple[str, ...]:
        """Capability platform names hosted by this registrar."""
        return AI_PLATFORMS

    def register_ocr(self, provider_type: str, factory: OcrModelFactory) -> None:
        """Register an OCR model factory for ``provider_type``."""
        _register_factory(self._ocr_factories, "OCR", provider_type, factory)

    def register_summary(
        self, provider_type: str, factory: SummaryModelFactory
    ) -> None:
        """Register a summary model factory for ``provider_type``."""
        _register_factory(self._summary_factories, "Summary", provider_type, factory)

    def register_embedding(
        self, provider_type: str, factory: EmbeddingModelFactory
    ) -> None:
        """Register an embedding model factory for ``provider_type``."""
        _register_factory(
            self._embedding_factories, "Embedding", provider_type, factory
        )

    def register_text(self, provider_type: str, factory: TextModelFactory) -> None:
        """Register a text generation model factory for ``provider_type``."""
        _register_factory(self._text_factories, "Text", provider_type, factory)

    @property
    def ocr_providers(self) -> tuple[str, ...]:
        """Registered OCR provider types in registration order."""
        return tuple(self._ocr_factories)

    @property
    def summary_providers(self) -> tuple[str, ...]:
        """Registered summary provider types in registration order."""
        return tuple(self._summary_factories)

    @property
    def embedding_providers(self) -> tuple[str, ...]:
        """Registered embedding provider types in registration order."""
        return tuple(self._embedding_factories)

    @property
    def text_providers(self) -> tuple[str, ...]:
        """Registered text generation provider types in registration order."""
        return tuple(self._text_factories)

    def create_ocr_model(self, config: AiComponentConfig) -> OcrModel | None:
        """Instantiate the configured OCR model wrapped with telemetry and concurrency limiting."""
        resolved = _instantiate_raw_model(
            self._ocr_factories, "OCR", config, config.ocr
        )
        if resolved is None:
            return None
        model, model_cfg = resolved
        if model_cfg.prompt_override is not None:
            model = PromptOverrideOcrModel(model, model_cfg.prompt_override)
        return ConcurrencyLimitedOcrModel(
            InstrumentedOcrModel(model),
            max_concurrency=model_cfg.max_concurrency,
        )

    def create_summary_model(self, config: AiComponentConfig) -> SummaryModel | None:
        """Instantiate the configured summary model wrapped with telemetry and concurrency limiting."""
        resolved = _instantiate_raw_model(
            self._summary_factories, "summary", config, config.summary
        )
        if resolved is None:
            return None
        model, model_cfg = resolved
        return ConcurrencyLimitedSummaryModel(
            InstrumentedSummaryModel(model),
            max_concurrency=model_cfg.max_concurrency,
        )

    def create_embedding_model(
        self, config: AiComponentConfig
    ) -> EmbeddingModel | None:
        """Instantiate the configured embedding model with validation, telemetry, and concurrency limiting."""
        resolved = _instantiate_raw_model(
            self._embedding_factories, "embedding", config, config.embedding
        )
        if resolved is None:
            return None
        model, model_cfg = resolved
        return ConcurrencyLimitedEmbeddingModel(
            InstrumentedEmbeddingModel(ValidatingEmbeddingModel(model)),
            max_concurrency=model_cfg.max_concurrency,
        )

    def create_text_model(
        self, config: AiComponentConfig
    ) -> TextGenerationModel | None:
        """Instantiate the configured text generation model wrapped with telemetry and concurrency limiting.

        When ``config.text`` is unset, falls back to ``config.summary`` if its
        provider supports structured text generation.
        """
        if config.text is not None:
            resolved = _instantiate_raw_model(
                self._text_factories, "text", config, config.text
            )
        elif config.summary is not None:
            key = config.provider_type(config.summary.provider).strip().lower()
            if key not in self._text_factories:
                return None
            resolved = _instantiate_raw_model(
                self._text_factories, "text", config, config.summary
            )
        else:
            return None
        if resolved is None:
            return None
        model, model_cfg = resolved
        return ConcurrencyLimitedTextGenerationModel(
            InstrumentedTextGenerationModel(model),
            max_concurrency=model_cfg.max_concurrency,
        )

    def apply_to_app(
        self,
        app: web.Application,
        config: AiComponentConfig,
    ) -> tuple[OcrModel | None, SummaryModel | None, EmbeddingModel | None]:
        """Instantiate configured AI models and bind them onto ``app``."""
        ocr_model = self.create_ocr_model(config)
        summary_model = self.create_summary_model(config)
        embedding_model = self.create_embedding_model(config)
        text_model = self.create_text_model(config)
        app[OCR_MODEL_KEY] = ocr_model
        app[SUMMARY_MODEL_KEY] = summary_model
        app[EMBEDDING_MODEL_KEY] = embedding_model
        app[TEXT_MODEL_KEY] = text_model
        return ocr_model, summary_model, embedding_model


class AiComponent:
    """Platform host component for AI model providers (OCR, summary, embedding, text)."""

    domain = "ai"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("http",)
    hosted_platforms: tuple[str, ...] = AI_PLATFORMS

    def __init__(self) -> None:
        self._registrar: AiRegistrar | None = None
        self._config: AiComponentConfig = AiComponentConfig()

    def get_platform_registrar(self) -> AiRegistrar:
        """Return the `AiRegistrar` initialized during `async_setup`."""
        assert self._registrar is not None
        return self._registrar

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Configure prompt overrides and initialize `AiRegistrar`."""
        self._config = AiComponentConfig.from_dict(dict(config))
        if self._config.prompts_dir:
            PROMPT_LOADER.configure(Path(self._config.prompts_dir))
        core.app[OCR_MODEL_KEY] = None
        core.app[SUMMARY_MODEL_KEY] = None
        core.app[EMBEDDING_MODEL_KEY] = None
        core.app[TEXT_MODEL_KEY] = None
        self._registrar = AiRegistrar()

    async def async_finalize_platforms(self, core: ServerCore) -> None:
        """Instantiate configured AI models and bind them onto ``core.app``."""
        self.get_platform_registrar().apply_to_app(core.app, self._config)

    async def async_start(self, core: ServerCore) -> None:
        """No-op; AI model clients are invoked on demand by workers and services."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; AI model registry holds no background tasks."""
