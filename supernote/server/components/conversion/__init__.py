"""On-demand `.note` to PNG and PDF conversion component (`ConversionComponent`).

Renders Supernote `.note` notebooks on demand into per-page PNG previews and
vector PDF exports stored in `CACHE_BUCKET`, and serves those cached artifacts
over signed download URLs. While core file routes handle durable user files and
the `processor` component runs the asynchronous background pipeline, this
component provides the synchronous conversion and export layer used by devices
and the Web UI—reusing `processor` for deduplicated PNG page rendering and
`supernote.notebook.PdfConverter` for PDF generation.

Provides `ConversionComponent`, `ConversionService`, `ConvertedBlob`, and
`CONVERSION_SERVICE_KEY` (for sibling components declaring
``dependencies = ("conversion",)``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.components.processor import PROCESSOR_SERVICE_KEY
from supernote.server.core import ServerCore

from .service import CONVERSION_SERVICE_KEY, ConversionService, ConvertedBlob

__all__ = [
    "CONVERSION_SERVICE_KEY",
    "ConversionComponent",
    "ConversionService",
    "ConvertedBlob",
]


class ConversionComponent:
    """Vertical component managing on-demand `.note` to PNG and PDF conversion."""

    domain = "conversion"
    dependencies: tuple[str, ...] = ("ai", "processor")
    platforms: tuple[str, ...] = ("http", "processor")

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Instantiate `ConversionService` and expose it via `CONVERSION_SERVICE_KEY`."""
        core.app[CONVERSION_SERVICE_KEY] = ConversionService(
            session_manager=core.session_manager,
            blob_storage=core.blob_storage,
            user_service=core.user_service,
            processor_service=core.app[PROCESSOR_SERVICE_KEY],
        )

    async def async_start(self, core: ServerCore) -> None:
        """No-op; conversions run on demand when requested."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; conversion service holds no background tasks."""
