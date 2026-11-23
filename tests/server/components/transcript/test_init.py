"""Unit tests for `supernote.server.components.transcript.TranscriptComponent`."""

from __future__ import annotations

from supernote.server.components.transcript import (
    TRANSCRIPT_SERVICE_KEY,
    TranscriptComponent,
    TranscriptService,
)
from supernote.server.core import Component, ComponentLoader, ServerCore


async def test_transcript_component_lifecycle(component_core: ServerCore) -> None:
    """Verify TranscriptComponent registers TranscriptService and supports idempotent lifecycle."""
    component = TranscriptComponent()
    assert isinstance(component, Component)
    assert component.domain == "transcript"
    assert component.dependencies == ()
    assert component.platforms == ("http", "mcp")

    loader = ComponentLoader()
    loader.register(component)

    await loader.async_setup_all(component_core, {})
    assert isinstance(component_core.app[TRANSCRIPT_SERVICE_KEY], TranscriptService)

    await loader.async_start_all(component_core)
    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_transcript_component_stop_after_setup_only(
    component_core: ServerCore,
) -> None:
    """Verify stopping after async_setup (without async_start) is clean."""
    loader = ComponentLoader()
    loader.register(TranscriptComponent())

    await loader.async_setup_all(component_core, {})
    await loader.async_stop_all(component_core)
