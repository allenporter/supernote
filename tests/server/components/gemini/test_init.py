"""Unit tests for `supernote.server.components.gemini` (`GeminiComponent`)."""

from __future__ import annotations

from supernote.server.components.ai import AiComponent
from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_gemini_component_registers_all_ai_platforms(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    loader = await load_components("gemini")
    component = loader.get("gemini")
    assert isinstance(component, Component)
    assert component.domain == "gemini"
    assert component.dependencies == ("ai",)
    assert component.platforms == ("ocr", "summary", "embedding", "text")

    ai_component = loader.get("ai")
    assert isinstance(ai_component, AiComponent)
    ai_registrar = ai_component.get_platform_registrar()

    assert ai_registrar.ocr_providers == ("gemini",)
    assert ai_registrar.summary_providers == ("gemini",)
    assert ai_registrar.embedding_providers == ("gemini",)
    assert ai_registrar.text_providers == ("gemini",)

    await loader.async_stop_all(component_core)
