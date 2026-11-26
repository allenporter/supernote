"""Configuration model for the background notebook processor component (`ProcessorConfig`)."""

from __future__ import annotations

from dataclasses import dataclass, field

from mashumaro.mixins.json import DataClassJSONMixin

from supernote.server.utils.image import DEFAULT_IMAGE_EXCLUDE_PATTERNS


@dataclass
class ProcessorConfig(DataClassJSONMixin):
    """Per-component settings for `supernote.server.components.processor`."""

    enabled: bool = True
    """Whether the background notebook processing pipeline is enabled."""

    enable_image_processing: bool = True
    """Whether standalone raster images (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`) are indexed by the background OCR pipeline."""

    image_include_patterns: list[str] = field(default_factory=list)
    """Optional VFS path globs restricting standalone image indexing (empty = allow all paths not excluded)."""

    image_exclude_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_IMAGE_EXCLUDE_PATTERNS)
    )
    """VFS path globs excluded from standalone image indexing (defaults to `MyStyle/**` and `EXPORT/**`)."""
