"""Unit tests for `supernote.server.components.gemini` (`GeminiComponent`)."""

from __future__ import annotations

from supernote.server.components.ai import (
    EMBEDDING_MODEL_KEY,
    OCR_MODEL_KEY,
    SUMMARY_MODEL_KEY,
    TEXT_MODEL_KEY,
    AiComponent,
)
from supernote.server.components.gemini import GeminiComponent
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig
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


async def test_gemini_component_shares_backend_across_four_roles_and_closes_on_unload(
    component_core: ServerCore,
    load_components: LoadComponents,
    gemini_base_url: str,
) -> None:
    """All four AI roles share one `GeminiBackend` and `ClientSession` and close both on unload."""
    component_core.config.ai = AiConfig(
        providers={
            "gemini": ProviderConfig(api_key="test-key", base_url=gemini_base_url)
        },
        ocr=ModelConfig(provider="gemini", model="gemini-2.0-flash"),
        summary=ModelConfig(provider="gemini", model="gemini-2.0-flash"),
        embedding=ModelConfig(provider="gemini", model="text-embedding-004"),
        text=ModelConfig(provider="gemini", model="gemini-2.0-flash-lite"),
    )
    loader = await load_components("gemini")

    ocr_model = component_core.app[OCR_MODEL_KEY]
    summary_model = component_core.app[SUMMARY_MODEL_KEY]
    embedding_model = component_core.app[EMBEDDING_MODEL_KEY]
    text_model = component_core.app[TEXT_MODEL_KEY]
    assert ocr_model is not None
    assert summary_model is not None
    assert embedding_model is not None
    assert text_model is not None

    comp = loader.get("gemini")
    assert isinstance(comp, GeminiComponent)
    session = comp.session
    assert session is not None
    assert not session.closed
    assert list(comp._backends) == ["gemini"]
    shared_backend = comp._backends["gemini"]
    assert shared_backend._session is session

    assert await ocr_model.extract_text(b"png", "hello") == "Handwritten text content"
    assert shared_backend._client is not None

    await loader.async_reconfigure(
        component_core, GeminiComponent(), {"enabled": False}
    )
    assert shared_backend._client is None
    assert session.closed
    assert comp.session is None
    assert comp._backends == {}
