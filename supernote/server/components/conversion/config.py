"""Configuration model for the `.note` to PNG and PDF conversion component (`ConversionConfig`)."""

from __future__ import annotations

from dataclasses import dataclass

from mashumaro.mixins.json import DataClassJSONMixin


@dataclass
class ConversionConfig(DataClassJSONMixin):
    """Per-component settings for `supernote.server.components.conversion`."""

    enabled: bool = True
    """Whether the `.note` conversion component is enabled."""

    notebook_preview: bool = True
    """Whether to generate and serve notebook page PNG previews for the Web UI and on-demand endpoints.

    Behavior across combinations with `enabled`, `processor.enabled`, and AI OCR:
    - `enabled=True, notebook_preview=True` (default): Background `PngConversionModule`
      renders page PNGs as `.note` files are uploaded, and on-demand PNG preview
      endpoints (`/api/extended/file/note/cover`, `/api/file/note/to/png`) serve
      cover and page images.
    - `enabled=True, notebook_preview=False`: On-demand PNG preview endpoints return
      empty results (`url=None` / `png_page_vo_list=[]`), while PDF export endpoints
      (`/api/file/note/to/pdf`) and `summary` handwriting conversions remain active.
      Background `PngConversionModule` is disabled unless an AI OCR model is configured
      (since `OcrModule` still requires rendered page PNGs for vision transcription).
    - `enabled=False`: Disables the entire `conversion` component (requires `transcript`
      and `summary` to also be disabled); neither PNG nor PDF conversion routes or
      `PngConversionModule` are loaded.
    """
