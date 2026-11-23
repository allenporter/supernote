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
from supernote.server.core import ServerCore
from supernote.server.keys import (
    EMBEDDING_MODEL_KEY,
    OCR_MODEL_KEY,
    SUMMARY_MODEL_KEY,
)
from supernote.server.utils.prompt_loader import PROMPT_LOADER

if TYPE_CHECKING:
    from aiohttp import web

    from supernote.server.config import ModelConfig, ServerConfig

__all__ = [
    "AI_PLATFORMS",
    "AiComponent",
    "AiRegistrar",
]

AI_PLATFORMS: tuple[str, ...] = ("ocr", "summary", "embedding")

_ModelT = TypeVar("_ModelT")
OcrModelFactory = Callable[["ServerConfig"], OcrModel | None]
SummaryModelFactory = Callable[["ServerConfig"], SummaryModel | None]
EmbeddingModelFactory = Callable[["ServerConfig"], EmbeddingModel | None]


def _normalize_provider_type(provider_type: str) -> str:
    normalized = provider_type.strip().lower()
    if not normalized:
        raise ValueError("AI provider type must be non-empty")
    return normalized


def _register_factory(
    registry: dict[str, Callable[[ServerConfig], _ModelT | None]],
    capability: str,
    provider_type: str,
    factory: Callable[[ServerConfig], _ModelT | None],
) -> None:
    key = _normalize_provider_type(provider_type)
    if key in registry:
        raise ValueError(f"{capability} provider {key!r} is already registered")
    registry[key] = factory


def _instantiate_raw_model(
    registry: Mapping[str, Callable[[ServerConfig], _ModelT | None]],
    capability: str,
    config: ServerConfig,
    model_cfg: ModelConfig | None,
) -> tuple[_ModelT, ModelConfig] | None:
    if model_cfg is None:
        return None
    raw_provider_type = config.ai.provider_type(model_cfg.provider)
    key = raw_provider_type.strip().lower()
    factory = registry.get(key)
    if factory is None:
        raise ValueError(
            f"Unsupported {capability} model provider type: {raw_provider_type!r}"
        )
    model = factory(config)
    if model is None:
        return None
    return model, model_cfg


class AiRegistrar:
    """Registrar passed into ``<component>.{ocr,summary,embedding}:async_setup_*``."""

    def __init__(self) -> None:
        self._ocr_factories: dict[str, OcrModelFactory] = {}
        self._summary_factories: dict[str, SummaryModelFactory] = {}
        self._embedding_factories: dict[str, EmbeddingModelFactory] = {}

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

    def create_ocr_model(self, config: ServerConfig) -> OcrModel | None:
        """Instantiate the configured OCR model wrapped with telemetry and concurrency limiting."""
        resolved = _instantiate_raw_model(
            self._ocr_factories, "OCR", config, config.ai.ocr
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

    def create_summary_model(self, config: ServerConfig) -> SummaryModel | None:
        """Instantiate the configured summary model wrapped with telemetry and concurrency limiting."""
        resolved = _instantiate_raw_model(
            self._summary_factories, "summary", config, config.ai.summary
        )
        if resolved is None:
            return None
        model, model_cfg = resolved
        return ConcurrencyLimitedSummaryModel(
            InstrumentedSummaryModel(model),
            max_concurrency=model_cfg.max_concurrency,
        )

    def create_embedding_model(self, config: ServerConfig) -> EmbeddingModel | None:
        """Instantiate the configured embedding model with validation, telemetry, and concurrency limiting."""
        resolved = _instantiate_raw_model(
            self._embedding_factories, "embedding", config, config.ai.embedding
        )
        if resolved is None:
            return None
        model, model_cfg = resolved
        return ConcurrencyLimitedEmbeddingModel(
            InstrumentedEmbeddingModel(ValidatingEmbeddingModel(model)),
            max_concurrency=model_cfg.max_concurrency,
        )

    def apply_to_app(
        self,
        app: web.Application,
        config: ServerConfig,
    ) -> tuple[OcrModel | None, SummaryModel | None, EmbeddingModel | None]:
        """Instantiate configured AI models and bind them onto ``app``."""
        ocr_model = self.create_ocr_model(config)
        summary_model = self.create_summary_model(config)
        embedding_model = self.create_embedding_model(config)
        app[OCR_MODEL_KEY] = ocr_model
        app[SUMMARY_MODEL_KEY] = summary_model
        app[EMBEDDING_MODEL_KEY] = embedding_model
        return ocr_model, summary_model, embedding_model


class AiComponent:
    """Platform host component for AI model providers (OCR, summary, embedding)."""

    domain = "ai"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("http",)
    hosted_platforms: tuple[str, ...] = AI_PLATFORMS

    def __init__(self) -> None:
        self._registrar: AiRegistrar | None = None

    def get_platform_registrar(self) -> AiRegistrar:
        """Return the `AiRegistrar` initialized during `async_setup`."""
        assert self._registrar is not None
        return self._registrar

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Configure prompt overrides and initialize `AiRegistrar`."""
        if core.config.prompts_dir:
            PROMPT_LOADER.configure(Path(core.config.prompts_dir))
        core.app[OCR_MODEL_KEY] = None
        core.app[SUMMARY_MODEL_KEY] = None
        core.app[EMBEDDING_MODEL_KEY] = None
        self._registrar = AiRegistrar()

    async def async_finalize_platforms(self, core: ServerCore) -> None:
        """Instantiate configured AI models and bind them onto ``core.app``."""
        self.get_platform_registrar().apply_to_app(core.app, core.config)

    async def async_start(self, core: ServerCore) -> None:
        """No-op; AI model clients are invoked on demand by workers and services."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; AI model registry holds no background tasks."""
