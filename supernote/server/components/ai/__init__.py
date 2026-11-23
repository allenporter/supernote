"""AI model platform host component (`AiComponent` and `AiRegistrar`).

Provides `AiComponent`, `AI_PLATFORMS` (``("ocr", "summary", "embedding")``),
and `AiRegistrar` (passed into
``<component>.<platform>:async_setup_<platform>(core, registrar)`` for vendor
backend components declaring capability platforms such as
``platforms = ("ocr", "summary", "embedding")`` or ``platforms = ("ocr",)``).
Applies cross-cutting wrappers (`ValidatingEmbeddingModel`,
`Instrumented*Model`, `ConcurrencyLimited*Model`) uniformly across all
registered providers, and registers the zero-dependency built-in ``fake``
provider directly.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

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
)
from supernote.server.ai.models.summary import (
    ConcurrencyLimitedSummaryModel,
    InstrumentedSummaryModel,
    SummaryModel,
)
from supernote.server.core import ServerCore
from supernote.server.keys import AI_REGISTRAR_KEY

if TYPE_CHECKING:
    from supernote.server.config import ServerConfig

__all__ = [
    "AI_PLATFORMS",
    "AI_REGISTRAR_KEY",
    "AiComponent",
    "AiRegistrar",
]

AI_PLATFORMS: tuple[str, ...] = ("ocr", "summary", "embedding")

OcrModelFactory = Callable[["ServerConfig"], OcrModel | None]
SummaryModelFactory = Callable[["ServerConfig"], SummaryModel | None]
EmbeddingModelFactory = Callable[["ServerConfig"], EmbeddingModel | None]


def _normalize_provider_type(provider_type: str) -> str:
    normalized = provider_type.strip().lower()
    if not normalized:
        raise ValueError("AI provider type must be non-empty")
    return normalized


class AiRegistrar:
    """Registrar passed into ``<component>.{ocr,summary,embedding}:async_setup_*``."""

    def __init__(self) -> None:
        self._ocr_factories: dict[str, OcrModelFactory] = {}
        self._summary_factories: dict[str, SummaryModelFactory] = {}
        self._embedding_factories: dict[str, EmbeddingModelFactory] = {}

    def register_ocr(self, provider_type: str, factory: OcrModelFactory) -> None:
        """Register an OCR model factory for ``provider_type``."""
        key = _normalize_provider_type(provider_type)
        if key in self._ocr_factories:
            raise ValueError(f"OCR provider {key!r} is already registered")
        self._ocr_factories[key] = factory

    def register_summary(
        self, provider_type: str, factory: SummaryModelFactory
    ) -> None:
        """Register a summary model factory for ``provider_type``."""
        key = _normalize_provider_type(provider_type)
        if key in self._summary_factories:
            raise ValueError(f"Summary provider {key!r} is already registered")
        self._summary_factories[key] = factory

    def register_embedding(
        self, provider_type: str, factory: EmbeddingModelFactory
    ) -> None:
        """Register an embedding model factory for ``provider_type``."""
        key = _normalize_provider_type(provider_type)
        if key in self._embedding_factories:
            raise ValueError(f"Embedding provider {key!r} is already registered")
        self._embedding_factories[key] = factory

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
        model_cfg = config.ai.ocr
        if model_cfg is None:
            return None
        provider_type = config.ai.provider_type(model_cfg.provider)
        factory = self._ocr_factories.get(provider_type)
        if factory is None:
            raise ValueError(f"Unsupported OCR model provider type: {provider_type!r}")
        model = factory(config)
        if model is None:
            return None
        return ConcurrencyLimitedOcrModel(
            InstrumentedOcrModel(model),
            max_concurrency=model_cfg.max_concurrency,
        )

    def create_summary_model(self, config: ServerConfig) -> SummaryModel | None:
        """Instantiate the configured summary model wrapped with telemetry and concurrency limiting."""
        model_cfg = config.ai.summary
        if model_cfg is None:
            return None
        provider_type = config.ai.provider_type(model_cfg.provider)
        factory = self._summary_factories.get(provider_type)
        if factory is None:
            raise ValueError(
                f"Unsupported summary model provider type: {provider_type!r}"
            )
        model = factory(config)
        if model is None:
            return None
        return ConcurrencyLimitedSummaryModel(
            InstrumentedSummaryModel(model),
            max_concurrency=model_cfg.max_concurrency,
        )

    def create_embedding_model(self, config: ServerConfig) -> EmbeddingModel | None:
        """Instantiate the configured embedding model with validation, telemetry, and concurrency limiting."""
        model_cfg = config.ai.embedding
        if model_cfg is None:
            return None
        provider_type = config.ai.provider_type(model_cfg.provider)
        factory = self._embedding_factories.get(provider_type)
        if factory is None:
            raise ValueError(
                f"Unsupported embedding model provider type: {provider_type!r}"
            )
        model = factory(config)
        if model is None:
            return None
        return ConcurrencyLimitedEmbeddingModel(
            InstrumentedEmbeddingModel(ValidatingEmbeddingModel(model)),
            max_concurrency=model_cfg.max_concurrency,
        )


def _register_builtin_fake_provider(registrar: AiRegistrar) -> None:
    """Register the zero-dependency built-in ``fake`` AI provider."""
    from supernote.server.ai.models.fake.embedding import (  # noqa: PLC0415
        create_embedding_model as create_fake_embedding_model,
    )
    from supernote.server.ai.models.fake.ocr import (  # noqa: PLC0415
        create_ocr_model as create_fake_ocr_model,
    )
    from supernote.server.ai.models.fake.summary import (  # noqa: PLC0415
        create_summary_model as create_fake_summary_model,
    )

    registrar.register_ocr("fake", create_fake_ocr_model)
    registrar.register_summary("fake", create_fake_summary_model)
    registrar.register_embedding("fake", create_fake_embedding_model)


class AiComponent:
    """Platform host component for AI model providers (OCR, summary, embedding)."""

    domain = "ai"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Initialize `AiRegistrar` with the built-in ``fake`` provider on ``core.app``."""
        registrar = AiRegistrar()
        _register_builtin_fake_provider(registrar)
        core.app[AI_REGISTRAR_KEY] = registrar

    async def async_start(self, core: ServerCore) -> None:
        """No-op; AI model clients are invoked on demand by workers and services."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; AI model registry holds no background tasks."""
