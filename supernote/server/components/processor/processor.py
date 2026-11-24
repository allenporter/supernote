"""Built-in `.note` pipeline stage registrations for `ProcessorComponent`."""

from __future__ import annotations

from supernote.server.components.processor import ProcessorRegistrar
from supernote.server.core import ServerCore
from supernote.server.keys import OCR_MODEL_KEY
from supernote.server.services.processor_modules.ocr import OcrModule
from supernote.server.services.processor_modules.page_hashing import PageHashingModule
from supernote.server.services.processor_modules.png_conversion import (
    PngConversionModule,
)


async def async_setup_processor(
    core: ServerCore,
    registrar: ProcessorRegistrar,
) -> None:
    """Register the core `.note` processing pipeline stages."""
    ocr_model = core.app.get(OCR_MODEL_KEY)
    png_enabled = (ocr_model is not None) or (
        core.config.web_enabled and core.config.web_notebook_preview
    )

    registrar.register_module(PageHashingModule(file_service=core.file_service))
    registrar.register_module(
        PngConversionModule(file_service=core.file_service, enabled=png_enabled)
    )
    registrar.register_module(
        OcrModule(file_service=core.file_service, ocr_model=ocr_model)
    )
