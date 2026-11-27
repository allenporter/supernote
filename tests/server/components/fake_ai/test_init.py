"""Unit tests for `supernote.server.components.fake_ai` (`FakeAiComponent`)."""

from __future__ import annotations

from supernote.server.ai.models.embedding import EmbeddingTaskType
from supernote.server.components.ai import AiComponent
from supernote.server.components.ai.config import AiComponentConfig
from supernote.server.config import ModelConfig, ProviderConfig
from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_fake_ai_component_registers_all_ai_platforms(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    loader = await load_components("fake_ai")
    component = loader.get("fake_ai")
    assert isinstance(component, Component)
    assert component.domain == "fake_ai"
    assert component.dependencies == ("ai",)
    assert component.platforms == ("ocr", "summary", "embedding", "text")

    ai_component = loader.get("ai")
    assert isinstance(ai_component, AiComponent)
    ai_registrar = ai_component.get_platform_registrar()

    assert ai_registrar.ocr_providers == ("fake_ai",)
    assert ai_registrar.summary_providers == ("fake_ai",)
    assert ai_registrar.embedding_providers == ("fake_ai",)
    assert ai_registrar.text_providers == ("fake_ai",)

    config = AiComponentConfig(
        providers={"fake_ai": ProviderConfig()},
        ocr=ModelConfig(provider="fake_ai", model="fake-ocr"),
        summary=ModelConfig(provider="fake_ai", model="fake-summary"),
        embedding=ModelConfig(provider="fake_ai", model="fake-embed"),
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

    await loader.async_stop_all(component_core)
