"""Unit tests for `supernote.server.components.ai` (`AiComponent` and `AiRegistrar`)."""

from __future__ import annotations

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import EmbeddingModel, EmbeddingTaskType
from supernote.server.ai.models.ocr import OcrModel
from supernote.server.ai.models.summary import SummaryModel, SummaryResponse
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
    def __init__(self, vector: list[float] | None = None) -> None:
        self._vector = vector if vector is not None else [1.0, 0.0]

    @property
    def provider(self) -> str:
        return "stub"

    @property
    def model_id(self) -> str:
        return "stub-embed"

    async def embed(self, text: str, task_type: EmbeddingTaskType) -> list[float]:
        return list(self._vector)


def test_ai_registrar_returns_none_when_capabilities_unconfigured() -> None:
    registrar = AiRegistrar()
    unconfigured = ServerConfig()
    assert registrar.create_ocr_model(unconfigured) is None
    assert registrar.create_summary_model(unconfigured) is None
    assert registrar.create_embedding_model(unconfigured) is None


async def test_ai_registrar_creates_and_invokes_registered_models() -> None:
    registrar = AiRegistrar()
    registrar.register_ocr("Stub", lambda _cfg: _StubOcrModel())
    registrar.register_summary("stub", lambda _cfg: _StubSummaryModel())
    registrar.register_embedding("stub", lambda _cfg: _StubEmbeddingModel())

    assert registrar.ocr_providers == ("stub",)
    assert registrar.summary_providers == ("stub",)
    assert registrar.embedding_providers == ("stub",)

    configured = ServerConfig(
        ai=AiConfig(
            providers={"my_stub": ProviderConfig(type="Stub")},
            ocr=ModelConfig(provider="my_stub", model="m1", max_concurrency=3),
            summary=ModelConfig(provider="my_stub", model="m2", max_concurrency=2),
            embedding=ModelConfig(provider="my_stub", model="m3", max_concurrency=4),
        )
    )

    ocr = registrar.create_ocr_model(configured)
    assert ocr is not None
    assert ocr.provider == "stub"
    assert ocr.model_id == "stub-ocr"
    assert await ocr.extract_text(b"png", "prompt") == "stub-text"

    summary = registrar.create_summary_model(configured)
    assert summary is not None
    assert summary.provider == "stub"
    assert summary.model_id == "stub-summary"
    assert await summary.summarize("prompt") == SummaryResponse(segments=[])

    embedding = registrar.create_embedding_model(configured)
    assert embedding is not None
    assert embedding.provider == "stub"
    assert embedding.model_id == "stub-embed"
    assert await embedding.embed("hello", EmbeddingTaskType.RETRIEVAL_QUERY) == [
        1.0,
        0.0,
    ]


async def test_ai_registrar_validates_embedding_vectors() -> None:
    registrar = AiRegistrar()
    registrar.register_embedding("bad", lambda _cfg: _StubEmbeddingModel([0.0, 0.0]))
    config = ServerConfig(
        ai=AiConfig(
            providers={"bad": ProviderConfig()},
            embedding=ModelConfig(provider="bad", model="m"),
        )
    )

    embedding = registrar.create_embedding_model(config)
    assert embedding is not None
    with pytest.raises(AIError, match="zero-norm vector"):
        await embedding.embed("hello", EmbeddingTaskType.RETRIEVAL_QUERY)


def test_ai_registrar_returns_none_when_factory_returns_none() -> None:
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


def test_ai_registrar_rejects_duplicate_and_blank_providers() -> None:
    registrar = AiRegistrar()
    registrar.register_ocr("noop", lambda _cfg: None)
    registrar.register_summary("noop", lambda _cfg: None)
    registrar.register_embedding("noop", lambda _cfg: None)

    with pytest.raises(ValueError, match="already registered"):
        registrar.register_ocr("noop", lambda _cfg: None)
    with pytest.raises(ValueError, match="already registered"):
        registrar.register_summary("noop", lambda _cfg: None)
    with pytest.raises(ValueError, match="already registered"):
        registrar.register_embedding("noop", lambda _cfg: None)
    with pytest.raises(ValueError, match="must be non-empty"):
        registrar.register_ocr("   ", lambda _cfg: None)


def test_ai_registrar_rejects_unknown_provider_types() -> None:
    registrar = AiRegistrar()
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
    assert registrar.platforms == AI_PLATFORMS
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
