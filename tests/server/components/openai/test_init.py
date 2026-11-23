"""Unit tests for `supernote.server.components.openai` (`OpenAIComponent`)."""

from __future__ import annotations

from supernote.server.components.ai import AI_REGISTRAR_KEY, AiComponent
from supernote.server.components.openai import OpenAIComponent
from supernote.server.core import Component, ComponentLoader, ServerCore


async def test_openai_component_registers_all_ai_platforms(
    component_core: ServerCore,
) -> None:
    component = OpenAIComponent()
    assert isinstance(component, Component)
    assert component.domain == "openai"
    assert component.dependencies == ("ai",)
    assert component.platforms == ("ocr", "summary", "embedding")

    loader = ComponentLoader()
    loader.register(AiComponent())
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    ai_registrar = component_core.app[AI_REGISTRAR_KEY]
    for platform in ai_registrar.platforms:
        await loader.async_load_platform(platform, component_core, ai_registrar)

    assert ai_registrar.ocr_providers == ("openai",)
    assert ai_registrar.summary_providers == ("openai",)
    assert ai_registrar.embedding_providers == ("openai",)

    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
