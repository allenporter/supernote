"""Unit tests for `supernote.server.components.processor.processor`."""

from __future__ import annotations

from supernote.models.base import TaskType
from supernote.server.components.processor import ProcessorRegistrar
from supernote.server.components.processor.processor import async_setup_processor
from supernote.server.core import ServerCore


async def test_async_setup_processor_registers_page_hashing_stage(
    component_core: ServerCore,
) -> None:
    """async_setup_processor registers PageHashingModule."""
    registrar = ProcessorRegistrar()
    await async_setup_processor(component_core, registrar)

    assert [m.task_type for m in registrar.modules] == [TaskType.PAGE_HASHING]
