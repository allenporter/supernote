"""Unit tests for `ProcessorComponent` lifecycle and `ProcessorRegistrar` platform host."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from types import ModuleType
from typing import Any

import pytest

from supernote.models.base import TaskType
from supernote.server.components import KNOWN_PLATFORMS
from supernote.server.components.ai import AiComponent
from supernote.server.components.processor import (
    ProcessorComponent,
    ProcessorRegistrar,
    ProcessorService,
)
from supernote.server.core import Component, ComponentLoader, PlatformHost, ServerCore
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.keys import PROCESSOR_SERVICE_KEY
from supernote.server.services.processor_modules import ProcessorModule, TaskScope


class _CustomStage(ProcessorModule):
    @property
    def name(self) -> str:
        return "CustomStage"

    @property
    def task_type(self) -> str:
        return "CUSTOM_POST_OCR"

    @property
    def scope(self) -> TaskScope:
        return TaskScope.FILE

    @property
    def depends_on(self) -> tuple[str, ...]:
        return (TaskType.PNG_CONVERSION,)

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        **kwargs: object,
    ) -> None:
        return None


async def test_processor_component_protocol_and_idempotent_lifecycle(
    component_core: ServerCore,
) -> None:
    """ProcessorComponent satisfies Component + PlatformHost and tears down idempotently."""
    comp = ProcessorComponent()
    assert set(comp.hosted_platforms) <= KNOWN_PLATFORMS
    assert isinstance(comp, Component)
    assert isinstance(comp, PlatformHost)

    loader = ComponentLoader()
    loader.register(AiComponent())
    loader.register(comp)

    await loader.async_setup_all(component_core, {})
    assert isinstance(component_core.app[PROCESSOR_SERVICE_KEY], ProcessorService)

    await loader.async_load_all_platforms(component_core)
    with pytest.raises(RuntimeError, match="after platforms are finalized"):
        comp.get_platform_registrar().register_module(_CustomStage())
    service = component_core.app[PROCESSOR_SERVICE_KEY]
    assert [m.task_type for m in service.task_graph.modules] == [
        TaskType.PAGE_HASHING,
        TaskType.PNG_CONVERSION,
    ]

    await loader.async_start_all(component_core)
    assert len(service.workers) == service.concurrency

    await loader.async_stop_all(component_core)
    await loader.async_stop_all(component_core)  # idempotent
    assert all(w.cancelled() or w.done() for w in service.workers)
    assert service.polling_task is not None and (
        service.polling_task.cancelled() or service.polling_task.done()
    )


async def test_processor_component_setup_to_stop_without_start(
    component_core: ServerCore,
) -> None:
    """ProcessorComponent supports async_setup -> async_stop without async_start."""
    loader = ComponentLoader()
    loader.register(AiComponent())
    loader.register(ProcessorComponent())

    await loader.async_setup_all(component_core, {})
    await loader.async_stop_all(component_core)


async def test_processor_platform_accepts_external_component_stages(
    component_core: ServerCore,
) -> None:
    """Another component declaring `platforms = ('processor',)` contributes stages into the DAG."""
    pkg_name = "tests.server.components.processor._synthetic_ext_pkg"
    platform_mod_name = f"{pkg_name}.processor"

    pkg_mod = ModuleType(pkg_name)
    pkg_mod.__package__ = pkg_name

    class _ExtComponent:
        domain = "synthetic_ext"
        dependencies: tuple[str, ...] = ("processor",)
        platforms: tuple[str, ...] = ("processor",)

        async def async_setup(
            self, core: ServerCore, config: Mapping[str, Any]
        ) -> None:
            return None

        async def async_start(self, core: ServerCore) -> None:
            return None

        async def async_stop(self, core: ServerCore) -> None:
            return None

    _ExtComponent.__module__ = pkg_name

    platform_mod = ModuleType(platform_mod_name)

    async def async_setup_processor(
        core: ServerCore, registrar: ProcessorRegistrar
    ) -> None:
        registrar.register_module(_CustomStage())

    setattr(platform_mod, "async_setup_processor", async_setup_processor)

    sys.modules[pkg_name] = pkg_mod
    sys.modules[platform_mod_name] = platform_mod
    try:
        loader = ComponentLoader()
        loader.register(AiComponent())
        loader.register(ProcessorComponent())
        loader.register(_ExtComponent())

        await loader.async_setup_all(component_core, {})
        await loader.async_load_all_platforms(component_core)

        service = component_core.app[PROCESSOR_SERVICE_KEY]
        assert "CUSTOM_POST_OCR" in {m.task_type for m in service.task_graph.modules}
        assert service.task_graph.ancestors("CUSTOM_POST_OCR") == frozenset(
            {"HASHING", "PNG_CONVERSION"}
        )
    finally:
        await loader.async_stop_all(component_core)
        sys.modules.pop(platform_mod_name, None)
        sys.modules.pop(pkg_name, None)
