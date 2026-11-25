"""Built-in `.note` pipeline stage registrations for `ProcessorComponent`."""

from __future__ import annotations

from supernote.server.components.ai import OCR_MODEL_KEY
from supernote.server.components.processor import ProcessorRegistrar
from supernote.server.core import ServerCore

from .page_hashing import PageHashingModule
from .png_conversion import PngConversionModule


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
