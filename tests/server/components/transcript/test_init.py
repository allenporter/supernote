"""Unit tests for `supernote.server.components.transcript.TranscriptComponent`."""

from __future__ import annotations

from supernote.server.components.transcript import (
    TRANSCRIPT_SERVICE_KEY,
    TranscriptService,
)
from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_transcript_component_lifecycle(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    """Verify TranscriptComponent registers TranscriptService and supports idempotent lifecycle."""
    loader = await load_components("transcript")
    component = loader.get("transcript")
    assert isinstance(component, Component)
    assert component.domain == "transcript"
    assert component.dependencies == ("ai",)
    assert component.platforms == ("http", "mcp", "processor")
    assert isinstance(component_core.app[TRANSCRIPT_SERVICE_KEY], TranscriptService)

    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_transcript_component_stop_after_setup_only(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    """Verify stopping after async_setup (without async_start) is clean."""
    loader = await load_components("transcript", start=False)
    await loader.async_stop_all(component_core)
