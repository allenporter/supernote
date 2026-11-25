"""Tests for `supernote.server.components.fake_ai.text`."""

from __future__ import annotations

from supernote.server.components.ai import TEXT_MODEL_KEY
from supernote.server.components.fake_ai.text import FakeTextGenerationModel
from supernote.server.config import AiConfig, ModelConfig
from supernote.server.core import ServerCore
from supernote.server.metrics import AIStage
from tests.server.components.conftest import LoadComponents


async def test_fake_text_generation_model_responses() -> None:
    model = FakeTextGenerationModel(responses=[{"page_ops": [{"slug": "index"}]}])
    result = await model.generate_json(
        "Compile this",
        response_schema={"type": "object"},
        stage=AIStage.WIKI_COMPILE,
    )
    assert result == {"page_ops": [{"slug": "index"}]}
    assert len(model.calls) == 1
    assert model.calls[0]["stage"] == AIStage.WIKI_COMPILE


async def test_fake_text_model_via_component_loader(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    component_core.config.ai = AiConfig(
        text=ModelConfig(provider="fake_ai", model="fake-wiki-v1"),
    )
    await load_components("ai", "fake_ai")

    model = component_core.app[TEXT_MODEL_KEY]
    assert model is not None
    assert model.provider == "fake_ai"
    assert model.model_id == "fake-wiki-v1"
    result = await model.generate_json("hello", response_schema={"type": "object"})
    assert result == {"page_ops": [], "log_entry": "Compiled (5 chars)"}
