"""Lifecycle tests for `WikiComponent`."""

from __future__ import annotations

from supernote.server.components import BUILTIN_COMPONENTS
from supernote.server.components.wiki import (
    WIKI_COMPILER_KEY,
    WIKI_EXPORT_SERVICE_KEY,
    WIKI_SERVICE_KEY,
    WikiCompilerWorker,
    WikiComponent,
    WikiExportService,
    WikiService,
)
from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_wiki_component_lifecycle(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    """WikiComponent loads via BUILTIN_COMPONENTS with ai/events deps, exposes keys, and stops idempotently."""
    loader = await load_components(
        "wiki",
        configs={"wiki": {"enabled": True, "max_pages_per_batch": 3}},
    )
    component = loader.get("wiki")
    assert isinstance(component, WikiComponent)
    assert isinstance(component, Component)
    assert component.domain == "wiki"
    assert component.dependencies == ("ai", "events")
    assert component.platforms == ("http", "mcp")
    assert loader.get("ai") is not None
    assert loader.get("events") is not None

    assert isinstance(component_core.app[WIKI_SERVICE_KEY], WikiService)
    assert isinstance(component_core.app[WIKI_EXPORT_SERVICE_KEY], WikiExportService)
    assert isinstance(component_core.app[WIKI_COMPILER_KEY], WikiCompilerWorker)
    assert component.config is not None
    assert component.config.max_pages_per_batch == 3

    await loader.async_stop_all(component_core)
    await component.async_stop(component_core)
    assert component.config is None


def test_wiki_registered_opt_in_in_builtin_components() -> None:
    """Wiki is registered in BUILTIN_COMPONENTS with default_enabled=False."""
    specs = {spec.domain: spec for spec in BUILTIN_COMPONENTS}
    assert "wiki" in specs
    assert specs["wiki"].default_enabled is False
