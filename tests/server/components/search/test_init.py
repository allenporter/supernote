"""Unit tests for `supernote.server.components.search.SearchComponent`."""

from __future__ import annotations

from supernote.server.components.fake_ai.embedding import FakeEmbeddingModel
from supernote.server.components.search import (
    SEARCH_SERVICE_KEY,
    SearchComponent,
    SearchService,
)
from supernote.server.core import Component, ComponentLoader, ServerCore
from supernote.server.keys import EMBEDDING_MODEL_KEY


async def test_search_component_lifecycle_binds_embedding_model_on_start(
    component_core: ServerCore,
) -> None:
    """Verify SearchComponent exposes SearchService and binds EMBEDDING_MODEL_KEY on start."""
    component = SearchComponent()
    assert isinstance(component, Component)
    assert component.domain == "search"
    assert component.dependencies == ()
    assert component.platforms == ("http", "mcp")

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    service = component_core.app[SEARCH_SERVICE_KEY]
    assert isinstance(service, SearchService)
    assert service.embedding_model is None

    # Simulate AiRegistrar populating EMBEDDING_MODEL_KEY between setup and start.
    embedding_model = FakeEmbeddingModel(model_id="fake-embed")
    component_core.app[EMBEDDING_MODEL_KEY] = embedding_model

    await loader.async_start_all(component_core)
    assert service.embedding_model is embedding_model

    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_search_component_stop_after_setup_only(
    component_core: ServerCore,
) -> None:
    """Verify stopping after async_setup (without async_start) is clean."""
    loader = ComponentLoader()
    loader.register(SearchComponent())

    await loader.async_setup_all(component_core, {})
    await loader.async_stop_all(component_core)
