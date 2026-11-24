"""Unit tests for `supernote.server.components.processor.processor`."""

from __future__ import annotations

import dataclasses

import pytest

from supernote.models.base import TaskType
from supernote.server.components.fake_ai.ocr import FakeOcrModel
from supernote.server.components.processor import ProcessorRegistrar
from supernote.server.components.processor.png_conversion import (
    PngConversionModule,
)
from supernote.server.components.processor.processor import async_setup_processor
from supernote.server.core import ServerCore
from supernote.server.keys import OCR_MODEL_KEY


@pytest.mark.parametrize(
    ("web_enabled", "web_notebook_preview", "has_ocr", "expected_png_enabled"),
    [
        (True, True, False, True),
        (True, False, False, False),
        (False, True, False, False),
        (False, False, True, True),
    ],
)
async def test_async_setup_processor_registers_builtin_stages_and_png_flag(
    component_core: ServerCore,
    web_enabled: bool,
    web_notebook_preview: bool,
    has_ocr: bool,
    expected_png_enabled: bool,
) -> None:
    """async_setup_processor registers core stages and toggles PNG by OCR/preview config."""
    core = dataclasses.replace(
        component_core,
        config=dataclasses.replace(
            component_core.config,
            web_enabled=web_enabled,
            web_notebook_preview=web_notebook_preview,
        ),
    )
    core.app[OCR_MODEL_KEY] = FakeOcrModel() if has_ocr else None

    registrar = ProcessorRegistrar()
    await async_setup_processor(core, registrar)

    task_types = [m.task_type for m in registrar.modules]
    assert task_types == [
        TaskType.PAGE_HASHING,
        TaskType.PNG_CONVERSION,
    ]
    png_mod = next(m for m in registrar.modules if isinstance(m, PngConversionModule))
    assert png_mod.enabled is expected_png_enabled
