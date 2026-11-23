"""Unit tests for `supernote.server.components.gemini` (`GeminiComponent`)."""

from __future__ import annotations

from supernote.server.components.ai import AiComponent
from supernote.server.components.gemini import GeminiComponent
from supernote.server.core import Component, ComponentLoader, ServerCore


async def test_gemini_component_registers_all_ai_platforms(
    component_core: ServerCore,
) -> None:
    component = GeminiComponent()
    assert isinstance(component, Component)
    assert component.domain == "gemini"
    assert component.dependencies == ("ai",)
    assert component.platforms == ("ocr", "summary", "embedding")

    ai_component = AiComponent()
    loader = ComponentLoader()
    loader.register(ai_component)
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    await loader.async_load_all_platforms(component_core)
    ai_registrar = ai_component.get_platform_registrar()

    assert ai_registrar.ocr_providers == ("gemini",)
    assert ai_registrar.summary_providers == ("gemini",)
    assert ai_registrar.embedding_providers == ("gemini",)

    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
