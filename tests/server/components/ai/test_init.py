"""Unit tests for `supernote.server.components.ai` (`AiComponent` and `AiRegistrar`)."""

from __future__ import annotations

import pytest

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
    SummaryResponse,
)
from supernote.server.components import KNOWN_PLATFORMS
from supernote.server.components.ai import (
    AI_PLATFORMS,
    AI_REGISTRAR_KEY,
    AiComponent,
    AiRegistrar,
)
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig, ServerConfig
from supernote.server.core import Component, ComponentLoader, ServerCore


class _StubOcrModel(OcrModel):
    @property
    def provider(self) -> str:
        return "stub"

    @property
    def model_id(self) -> str:
        return "stub-ocr"

    async def extract_text(self, png_data: bytes, prompt: str) -> str:
        return "stub-text"


class _StubSummaryModel(SummaryModel):
    @property
    def provider(self) -> str:
        return "stub"

    @property
    def model_id(self) -> str:
        return "stub-summary"

    async def summarize(self, prompt: str) -> SummaryResponse:
        return SummaryResponse(segments=[])


class _StubEmbeddingModel(EmbeddingModel):
    @property
    def provider(self) -> str:
        return "stub"

    @property
    def model_id(self) -> str:
        return "stub-embed"

    async def embed(self, text: str, task_type: str | None = None) -> list[float]:
        return [1.0, 0.0]


def test_ai_registrar_registers_and_wraps_models() -> None:
    registrar = AiRegistrar()
    registrar.register_ocr("Stub", lambda _cfg: _StubOcrModel())
    registrar.register_summary("stub", lambda _cfg: _StubSummaryModel())
    registrar.register_embedding("stub", lambda _cfg: _StubEmbeddingModel())

    assert registrar.ocr_providers == ("stub",)
    assert registrar.summary_providers == ("stub",)
    assert registrar.embedding_providers == ("stub",)

    unconfigured = ServerConfig()
    assert registrar.create_ocr_model(unconfigured) is None
    assert registrar.create_summary_model(unconfigured) is None
    assert registrar.create_embedding_model(unconfigured) is None

    configured = ServerConfig(
        ai=AiConfig(
            providers={"my_stub": ProviderConfig(type="stub")},
            ocr=ModelConfig(provider="my_stub", model="m1", max_concurrency=3),
            summary=ModelConfig(provider="my_stub", model="m2", max_concurrency=2),
            embedding=ModelConfig(provider="my_stub", model="m3", max_concurrency=4),
        )
    )

    ocr = registrar.create_ocr_model(configured)
    assert isinstance(ocr, ConcurrencyLimitedOcrModel)
    assert isinstance(ocr._model, InstrumentedOcrModel)
    assert isinstance(ocr._model._model, _StubOcrModel)

    summary = registrar.create_summary_model(configured)
    assert isinstance(summary, ConcurrencyLimitedSummaryModel)
    assert isinstance(summary._model, InstrumentedSummaryModel)
    assert isinstance(summary._model._model, _StubSummaryModel)

    embedding = registrar.create_embedding_model(configured)
    assert isinstance(embedding, ConcurrencyLimitedEmbeddingModel)
    assert isinstance(embedding._model, InstrumentedEmbeddingModel)
    assert isinstance(embedding._model._model, ValidatingEmbeddingModel)
    assert isinstance(embedding._model._model._model, _StubEmbeddingModel)


def test_ai_registrar_handles_none_factory_duplicates_and_unknown_providers() -> None:
    registrar = AiRegistrar()
    registrar.register_ocr("noop", lambda _cfg: None)
    registrar.register_summary("noop", lambda _cfg: None)
    registrar.register_embedding("noop", lambda _cfg: None)

    noop_cfg = ServerConfig(
        ai=AiConfig(
            providers={"noop": ProviderConfig()},
            ocr=ModelConfig(provider="noop", model="m"),
            summary=ModelConfig(provider="noop", model="m"),
            embedding=ModelConfig(provider="noop", model="m"),
        )
    )
    assert registrar.create_ocr_model(noop_cfg) is None
    assert registrar.create_summary_model(noop_cfg) is None
    assert registrar.create_embedding_model(noop_cfg) is None

    with pytest.raises(ValueError, match="already registered"):
        registrar.register_ocr("noop", lambda _cfg: None)
    with pytest.raises(ValueError, match="already registered"):
        registrar.register_summary("noop", lambda _cfg: None)
    with pytest.raises(ValueError, match="already registered"):
        registrar.register_embedding("noop", lambda _cfg: None)
    with pytest.raises(ValueError, match="must be non-empty"):
        registrar.register_ocr("   ", lambda _cfg: None)

    missing_cfg = ServerConfig(
        ai=AiConfig(
            providers={"unknown": ProviderConfig()},
            ocr=ModelConfig(provider="unknown", model="m"),
            summary=ModelConfig(provider="unknown", model="m"),
            embedding=ModelConfig(provider="unknown", model="m"),
        )
    )
    with pytest.raises(ValueError, match="Unsupported OCR model provider type"):
        registrar.create_ocr_model(missing_cfg)
    with pytest.raises(ValueError, match="Unsupported summary model provider type"):
        registrar.create_summary_model(missing_cfg)
    with pytest.raises(ValueError, match="Unsupported embedding model provider type"):
        registrar.create_embedding_model(missing_cfg)


async def test_ai_component_lifecycle_registers_builtin_fake_provider(
    component_core: ServerCore,
) -> None:
    assert AI_PLATFORMS == ("ocr", "summary", "embedding")
    assert set(AI_PLATFORMS) <= KNOWN_PLATFORMS

    component = AiComponent()
    assert isinstance(component, Component)
    assert component.domain == "ai"
    assert component.dependencies == ()
    assert component.platforms == ()

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    registrar = component_core.app[AI_REGISTRAR_KEY]
    assert isinstance(registrar, AiRegistrar)
    assert registrar.ocr_providers == ("fake",)
    assert registrar.summary_providers == ("fake",)
    assert registrar.embedding_providers == ("fake",)

    fake_cfg = ServerConfig(
        ai=AiConfig(
            providers={"fake": ProviderConfig()},
            ocr=ModelConfig(provider="fake", model="fake-ocr"),
            summary=ModelConfig(provider="fake", model="fake-summary"),
            embedding=ModelConfig(provider="fake", model="fake-embed"),
        )
    )
    assert registrar.create_ocr_model(fake_cfg) is not None
    assert registrar.create_summary_model(fake_cfg) is not None
    assert registrar.create_embedding_model(fake_cfg) is not None

    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
