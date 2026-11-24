"""Tests for `supernote.server.components.gemini.text`."""

from __future__ import annotations

import json

import pytest

from supernote.server.ai.base import AIError
from supernote.server.components.ai import TEXT_MODEL_KEY
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig
from supernote.server.core import ServerCore
from supernote.server.metrics import AIStage
from tests.server.components.conftest import LoadComponents

from .conftest import FakeGeminiServer

SCHEMA = {
    "type": "object",
    "properties": {"page_ops": {"type": "array"}},
    "required": ["page_ops"],
}


async def test_gemini_text_model_via_component_loader(
    component_core: ServerCore,
    load_components: LoadComponents,
    gemini_base_url: str,
    fake_gemini: FakeGeminiServer,
) -> None:
    component_core.config.ai = AiConfig(
        providers={
            "gemini": ProviderConfig(api_key="test-key", base_url=gemini_base_url)
        },
        text=ModelConfig(provider="gemini", model="gemini-2.5-flash"),
    )
    await load_components("ai", "gemini")

    model = component_core.app[TEXT_MODEL_KEY]
    assert model is not None
    assert model.provider == "gemini"
    assert model.model_id == "gemini-2.5-flash"

    fake_gemini.text = json.dumps({"page_ops": [{"slug": "topics/ai"}]})
    result = await model.generate_json(
        "Compile diff",
        response_schema=SCHEMA,
        stage=AIStage.WIKI_COMPILE,
    )
    assert result == {"page_ops": [{"slug": "topics/ai"}]}


async def test_gemini_text_model_invalid_json_raises(
    component_core: ServerCore,
    load_components: LoadComponents,
    gemini_base_url: str,
    fake_gemini: FakeGeminiServer,
) -> None:
    component_core.config.ai = AiConfig(
        providers={
            "gemini": ProviderConfig(api_key="test-key", base_url=gemini_base_url)
        },
        text=ModelConfig(provider="gemini", model="gemini-2.5-flash"),
    )
    await load_components("ai", "gemini")

    model = component_core.app[TEXT_MODEL_KEY]
    assert model is not None
    fake_gemini.text = "not valid json"
    with pytest.raises(AIError):
        await model.generate_json("Compile diff", response_schema=SCHEMA)
