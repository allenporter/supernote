"""Unit tests for `supernote.server.components.search.SearchComponent`."""

from __future__ import annotations

from supernote.server.components.ai import EMBEDDING_MODEL_KEY, AiComponent
from supernote.server.components.fake_ai.embedding import FakeEmbeddingModel
from supernote.server.components.search import (
    SEARCH_SERVICE_KEY,
    SearchComponent,
    SearchService,
)
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig
from supernote.server.core import Component, ComponentLoader, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_search_component_lifecycle_binds_embedding_model_on_start(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    """Verify SearchComponent loads via load_components and binds the configured embedding model."""
    component_core.config.ai = AiConfig(
        providers={"fake": ProviderConfig(type="fake")},
        embedding=ModelConfig(provider="fake", model="fake-embed"),
    )
    loader = await load_components("search", "fake_ai")
    component = loader.get("search")
    assert isinstance(component, Component)
    assert component.domain == "search"
    assert component.dependencies == ("ai",)
    assert component.platforms == ("http", "mcp", "processor")

    service = component_core.app[SEARCH_SERVICE_KEY]
    assert isinstance(service, SearchService)
    assert service.embedding_model is component_core.app[EMBEDDING_MODEL_KEY]
    assert service.embedding_model is not None

    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_search_component_stop_after_setup_only(
    component_core: ServerCore,
) -> None:
    """Verify stopping after async_setup (without async_start) is clean."""
    loader = ComponentLoader()
    loader.register(AiComponent())
    loader.register(SearchComponent())

    await loader.async_setup_all(component_core, {})
    component_core.app[EMBEDDING_MODEL_KEY] = FakeEmbeddingModel(model_id="fake-embed")
    await loader.async_stop_all(component_core)
