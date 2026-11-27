"""Unit tests for `supernote.server.components.note_metadata.NoteMetadataComponent`."""

from __future__ import annotations

from supernote.server.components.note_metadata import (
    NOTE_METADATA_SERVICE_KEY,
    NoteMetadataService,
)
from supernote.server.core import Component, ServerCore
from tests.server.components.conftest import LoadComponents


async def test_note_metadata_component_lifecycle(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    """Verify NoteMetadataComponent registers NoteMetadataService and supports idempotent lifecycle."""
    loader = await load_components("note_metadata")
    component = loader.get("note_metadata")
    assert isinstance(component, Component)
    assert component.domain == "note_metadata"
    assert component.dependencies == ("processor",)
    assert component.platforms == ("http", "processor")
    service = component_core.app[NOTE_METADATA_SERVICE_KEY]
    assert isinstance(service, NoteMetadataService)

    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)


async def test_note_metadata_component_stop_after_setup_only(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    """Verify stopping after async_setup (without async_start) is clean."""
    loader = await load_components("note_metadata", start=False)
    await loader.async_stop_all(component_core)
