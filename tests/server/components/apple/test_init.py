"""Unit tests for `supernote.server.components.apple` (`AppleComponent`)."""

from __future__ import annotations

from supernote.server.components.ai import AiComponent
from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_apple_component_registers_ocr_platform(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    loader = await load_components("apple")
    component = loader.get("apple")
    assert isinstance(component, Component)
    assert component.domain == "apple"
    assert component.dependencies == ("ai",)
    assert component.platforms == ("ocr",)

    ai_component = loader.get("ai")
    assert isinstance(ai_component, AiComponent)
    ai_registrar = ai_component.get_platform_registrar()

    assert ai_registrar.ocr_providers == ("apple",)
    assert ai_registrar.summary_providers == ()
    assert ai_registrar.embedding_providers == ()

    await loader.async_stop_all(component_core)
