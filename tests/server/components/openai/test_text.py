"""Tests for `supernote.server.components.openai.text`."""

from __future__ import annotations

import json

import pytest

from supernote.server.ai.base import AIError
from supernote.server.components.ai import TEXT_MODEL_KEY
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig
from supernote.server.core import ServerCore
from supernote.server.metrics import AIStage
from tests.server.components.conftest import LoadComponents

from .conftest import FakeOpenAIServer

SCHEMA = {
    "type": "object",
    "properties": {"page_ops": {"type": "array"}},
    "required": ["page_ops"],
}


async def test_openai_text_model_via_component_loader(
    component_core: ServerCore,
    load_components: LoadComponents,
    openai_base_url: str,
    fake_openai: FakeOpenAIServer,
) -> None:
    component_core.config.ai = AiConfig(
        providers={"openai": ProviderConfig(base_url=openai_base_url)},
        text=ModelConfig(provider="openai", model="gpt-4o-mini"),
    )
    await load_components("ai", "openai")

    model = component_core.app[TEXT_MODEL_KEY]
    assert model is not None
    assert model.provider == "openai"
    assert model.model_id == "gpt-4o-mini"

    fake_openai.chat_content = json.dumps({"page_ops": []})
    result = await model.generate_json(
        "Compile diff",
        response_schema=SCHEMA,
        schema_name="wiki_compile_plan",
        stage=AIStage.WIKI_COMPILE,
    )
    assert result == {"page_ops": []}
    (_, _, payload) = fake_openai.requests[0]
    assert payload == {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "Compile diff"}]}
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "wiki_compile_plan",
                "schema": SCHEMA,
            },
        },
    }


async def test_openai_text_model_invalid_json_raises(
    component_core: ServerCore,
    load_components: LoadComponents,
    openai_base_url: str,
    fake_openai: FakeOpenAIServer,
) -> None:
    component_core.config.ai = AiConfig(
        providers={"openai": ProviderConfig(base_url=openai_base_url)},
        text=ModelConfig(provider="openai", model="gpt-4o-mini"),
    )
    await load_components("ai", "openai")

    model = component_core.app[TEXT_MODEL_KEY]
    assert model is not None
    fake_openai.chat_content = ""
    with pytest.raises(AIError):
        await model.generate_json("Compile diff", response_schema=SCHEMA)


async def test_openai_text_model_falls_back_to_summary(
    component_core: ServerCore,
    load_components: LoadComponents,
    openai_base_url: str,
    fake_openai: FakeOpenAIServer,
) -> None:
    component_core.config.ai = AiConfig(
        providers={"openai": ProviderConfig(base_url=openai_base_url)},
        summary=ModelConfig(provider="openai", model="gpt-4o-mini"),
    )
    await load_components("ai", "openai")

    model = component_core.app[TEXT_MODEL_KEY]
    assert model is not None
    assert model.provider == "openai"
    assert model.model_id == "gpt-4o-mini"

    fake_openai.chat_content = json.dumps({"page_ops": []})
    assert await model.generate_json("Compile diff", response_schema=SCHEMA) == {
        "page_ops": []
    }
