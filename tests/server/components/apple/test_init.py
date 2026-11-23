"""Unit tests for `supernote.server.components.apple` (`AppleComponent`)."""

from __future__ import annotations

from supernote.server.components.ai import AI_REGISTRAR_KEY, AiComponent
from supernote.server.components.apple import AppleComponent
from supernote.server.core import Component, ComponentLoader, ServerCore


async def test_apple_component_registers_ocr_platform(
    component_core: ServerCore,
) -> None:
    component = AppleComponent()
    assert isinstance(component, Component)
    assert component.domain == "apple"
    assert component.dependencies == ("ai",)
    assert component.platforms == ("ocr",)

    loader = ComponentLoader()
    loader.register(AiComponent())
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    ai_registrar = component_core.app[AI_REGISTRAR_KEY]
    for platform in ai_registrar.platforms:
        await loader.async_load_platform(platform, component_core, ai_registrar)

    assert ai_registrar.ocr_providers == ("apple",)
    assert ai_registrar.summary_providers == ()
    assert ai_registrar.embedding_providers == ()

    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
