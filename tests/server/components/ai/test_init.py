"""Unit tests for `supernote.server.components.ai` (`AiComponent` and `AiRegistrar`)."""

from __future__ import annotations

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import EmbeddingModel, EmbeddingTaskType
from supernote.server.components import KNOWN_PLATFORMS
from supernote.server.components.ai import (
    AI_PLATFORMS,
    AiComponent,
    AiRegistrar,
)
from supernote.server.components.fake_ai.embedding import (
    create_embedding_model as create_fake_embedding_model,
)
from supernote.server.components.fake_ai.ocr import (
    FakeOcrModel,
)
from supernote.server.components.fake_ai.ocr import (
    create_ocr_model as create_fake_ocr_model,
)
from supernote.server.components.fake_ai.summary import (
    create_summary_model as create_fake_summary_model,
)
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig, ServerConfig
from supernote.server.core import Component, ComponentLoader, PlatformHost, ServerCore


class _ZeroVectorEmbeddingModel(EmbeddingModel):
    @property
    def provider(self) -> str:
        return "bad"

    @property
    def model_id(self) -> str:
        return "bad-embed"

    async def embed(self, text: str, task_type: EmbeddingTaskType) -> list[float]:
        return [0.0, 0.0]


def test_ai_registrar_returns_none_when_capabilities_unconfigured() -> None:
    registrar = AiRegistrar()
    unconfigured = ServerConfig()
    assert registrar.create_ocr_model(unconfigured) is None
    assert registrar.create_summary_model(unconfigured) is None
    assert registrar.create_embedding_model(unconfigured) is None


async def test_ai_registrar_creates_and_invokes_registered_models() -> None:
    registrar = AiRegistrar()
    registrar.register_ocr("Fake", create_fake_ocr_model)
    registrar.register_summary("fake", create_fake_summary_model)
    registrar.register_embedding("fake", create_fake_embedding_model)

    assert registrar.ocr_providers == ("fake",)
    assert registrar.summary_providers == ("fake",)
    assert registrar.embedding_providers == ("fake",)

    configured = ServerConfig(
        ai=AiConfig(
            providers={"local_fake": ProviderConfig(type="Fake")},
            ocr=ModelConfig(provider="local_fake", model="fake-ocr", max_concurrency=3),
            summary=ModelConfig(
                provider="local_fake", model="fake-summary", max_concurrency=2
            ),
            embedding=ModelConfig(
                provider="local_fake", model="fake-embed", max_concurrency=4
            ),
        )
    )

    ocr = registrar.create_ocr_model(configured)
    assert ocr is not None
    assert ocr.provider == "local_fake"
    assert ocr.model_id == "fake-ocr"
    assert await ocr.extract_text(b"png", "prompt")

    summary = registrar.create_summary_model(configured)
    assert summary is not None
    assert summary.provider == "local_fake"
    assert summary.model_id == "fake-summary"
    assert (await summary.summarize("prompt")).segments

    embedding = registrar.create_embedding_model(configured)
    assert embedding is not None
    assert embedding.provider == "local_fake"
    assert embedding.model_id == "fake-embed"
    vector = await embedding.embed("hello", EmbeddingTaskType.RETRIEVAL_QUERY)
    assert len(vector) > 0


async def test_ai_registrar_validates_embedding_vectors() -> None:
    registrar = AiRegistrar()
    registrar.register_embedding("bad", lambda _cfg: _ZeroVectorEmbeddingModel())
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


async def test_ai_registrar_applies_ocr_prompt_override() -> None:
    inner = FakeOcrModel(model_id="DeepSeek-OCR-8bit", provider="local")
    registrar = AiRegistrar()
    registrar.register_ocr("local", lambda _cfg: inner)

    config = ServerConfig(
        ai=AiConfig(
            providers={"local": ProviderConfig()},
            ocr=ModelConfig(
                provider="local",
                model="DeepSeek-OCR-8bit",
                max_concurrency=1,
                prompt_override="Convert the document to markdown.",
            ),
        )
    )

    ocr = registrar.create_ocr_model(config)
    assert ocr is not None
    await ocr.extract_text(b"png", "long composed prompt")
    assert inner.calls == [(b"png", "Convert the document to markdown.")]


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


async def test_ai_component_lifecycle_exposes_empty_registrar(
    component_core: ServerCore,
) -> None:
    assert AI_PLATFORMS == ("ocr", "summary", "embedding")
    assert set(AI_PLATFORMS) <= KNOWN_PLATFORMS

    component = AiComponent()
    assert isinstance(component, Component)
    assert isinstance(component, PlatformHost)
    assert component.domain == "ai"
    assert component.dependencies == ()
    assert component.platforms == ("http",)
    assert component.hosted_platforms == AI_PLATFORMS

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    registrar = component.get_platform_registrar()
    assert isinstance(registrar, AiRegistrar)
    assert registrar.platforms == AI_PLATFORMS
    assert registrar.ocr_providers == ()
    assert registrar.summary_providers == ()
    assert registrar.embedding_providers == ()

    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
