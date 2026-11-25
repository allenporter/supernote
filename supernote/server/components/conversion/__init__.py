"""On-demand `.note` to PNG and PDF conversion component (`ConversionComponent`).

### Role & Responsibilities

Provides synchronous, request-driven rendering and export of `.note` notebooks into
standard visual formats (per-page PNG previews and vector PDF documents) cached in
`CACHE_BUCKET`—replacing the external TCP `QTServer` from Ratta's Private Cloud stack.

- **Boundary with core (`FileService` / `routes/oss.py`)**: Core owns durable user-file
  uploads, downloads, and hardware sync in `USER_DATA_BUCKET`. This component only handles
  derived visual artifacts in `CACHE_BUCKET`.
- **Boundary with `processor` (`ProcessorService`)**: `processor` runs the asynchronous,
  event-driven background pipeline. This component (`dependencies = ("processor",)`) is
  the synchronous facade that delegates missing PNG page renders to `ProcessorService`
  (sharing deduplicated page PNGs with OCR) and renders PDFs in worker threads via
  `supernote.notebook.PdfConverter`.
- **HTTP surface (`platforms = ("http",)`)**:
  - **Conversion triggers** (`POST /api/file/note/to/png`, `POST /api/file/note/to/pdf`,
    `POST /api/extended/file/note/cover`): render on demand into `CACHE_BUCKET` and return
    HMAC-signed download URLs.
  - **Cache delivery** (`GET /api/oss/png/{file_id}/{page_no}`, `GET /api/oss/pdf/{file_id}`):
    verify signatures and stream previously converted blobs from `CACHE_BUCKET` (returning
    `404` on cache miss; they do not render on the fly).

### Internal Python API

Components needing on-demand PNG/PDF conversion should declare
``dependencies = ("conversion",)`` and access `CONVERSION_SERVICE_KEY` on `core.app`:

```python
from supernote.server.components.conversion import CONVERSION_SERVICE_KEY

conversion = core.app[CONVERSION_SERVICE_KEY]
pages = await conversion.convert_note_to_png(user_email, file_id)
```
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore
from supernote.server.keys import PROCESSOR_SERVICE_KEY

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
    dependencies: tuple[str, ...] = ("processor",)
    platforms: tuple[str, ...] = ("http",)

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
