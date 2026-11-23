"""Unit tests for `supernote.server.components.fake_ai` (`FakeAiComponent`)."""

from __future__ import annotations

from supernote.server.ai.models.embedding import EmbeddingTaskType
from supernote.server.components.ai import AiComponent
from supernote.server.components.fake_ai import FakeAiComponent
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig, ServerConfig
from supernote.server.core import Component, ComponentLoader, ServerCore


async def test_fake_ai_component_registers_all_ai_platforms(
    component_core: ServerCore,
) -> None:
    component = FakeAiComponent()
    assert isinstance(component, Component)
    assert component.domain == "fake_ai"
    assert component.dependencies == ("ai",)
    assert component.platforms == ("ocr", "summary", "embedding")

    ai_component = AiComponent()
    loader = ComponentLoader()
    loader.register(ai_component)
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    await loader.async_load_all_platforms(component_core)
    ai_registrar = ai_component.get_platform_registrar()

    assert ai_registrar.ocr_providers == ("fake",)
    assert ai_registrar.summary_providers == ("fake",)
    assert ai_registrar.embedding_providers == ("fake",)

    config = ServerConfig(
        ai=AiConfig(
            providers={"fake": ProviderConfig()},
            ocr=ModelConfig(provider="fake", model="fake-ocr"),
            summary=ModelConfig(provider="fake", model="fake-summary"),
            embedding=ModelConfig(provider="fake", model="fake-embed"),
        )
    )
    ocr = ai_registrar.create_ocr_model(config)
    summary = ai_registrar.create_summary_model(config)
    embedding = ai_registrar.create_embedding_model(config)

    assert ocr is not None
    assert await ocr.extract_text(b"png", "prompt") == "Transcribed (3 bytes)"
    assert summary is not None
    assert (await summary.summarize("prompt")).segments
    assert embedding is not None
    assert len(await embedding.embed("hello", EmbeddingTaskType.RETRIEVAL_QUERY)) > 0

    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
