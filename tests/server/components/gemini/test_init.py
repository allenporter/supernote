"""Unit tests for `supernote.server.components.gemini` (`GeminiComponent`)."""

from __future__ import annotations

from supernote.server.components.ai import AiComponent
from supernote.server.components.gemini import GeminiComponent
from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_gemini_component_registers_all_ai_platforms(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    loader = await load_components(
        "gemini",
        configs={
            "gemini": {
                "enabled": True,
                "api_key": "test-gemini-key",
                "base_url": "https://generativelanguage.googleapis.com",
            }
        },
    )
    component = loader.get("gemini")
    assert isinstance(component, GeminiComponent)
    assert isinstance(component, Component)
    assert component.domain == "gemini"
    assert component.dependencies == ("ai",)
    assert component.platforms == ("ocr", "summary", "embedding", "text")
    assert component._config.api_key == "test-gemini-key"
    assert component._config.providers["gemini"].api_key == "test-gemini-key"

    ai_component = loader.get("ai")
    assert isinstance(ai_component, AiComponent)
    ai_registrar = ai_component.get_platform_registrar()

    assert ai_registrar.ocr_providers == ("gemini",)
    assert ai_registrar.summary_providers == ("gemini",)
    assert ai_registrar.embedding_providers == ("gemini",)
    assert ai_registrar.text_providers == ("gemini",)

    await loader.async_stop_all(component_core)
