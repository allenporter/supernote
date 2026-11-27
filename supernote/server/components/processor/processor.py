"""Built-in `.note` pipeline stage registrations for `ProcessorComponent`."""

from __future__ import annotations

from supernote.server.components.processor import ProcessorRegistrar
from supernote.server.core import ServerCore

from .page_hashing import PageHashingModule


async def async_setup_processor(
    core: ServerCore,
    registrar: ProcessorRegistrar,
) -> None:
    """Register the core `.note` processing pipeline stages."""
    registrar.register_module(PageHashingModule(file_service=core.file_service))
