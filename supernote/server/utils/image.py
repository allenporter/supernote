"""Image format detection and PNG normalization helpers.

Provides EXIF-aware decoding, bounding-box downscaling, and PNG encoding via
Pillow for serving page images over MCP and normalizing standalone images in
the processing pipeline.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps, UnidentifiedImageError

__all__ = [
    "DEFAULT_IMAGE_EXCLUDE_PATTERNS",
    "DEFAULT_MAX_IMAGE_DIMENSION",
    "MAX_ALLOWED_IMAGE_DIMENSION",
    "MAX_SOURCE_IMAGE_BYTES",
    "MIN_ALLOWED_IMAGE_DIMENSION",
    "STANDALONE_IMAGE_PAGE_ID",
    "is_image_filename",
    "is_indexable_image_path",
    "is_processable_filename",
    "normalize_image_to_png",
]

# Aligns with the raster image MIME types allowed inline in `routes/oss.py`
# (`image/png`, `image/jpeg`, `image/gif`, `image/webp`, `image/bmp`).
_SUPPORTED_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
)

STANDALONE_IMAGE_PAGE_ID: str = "img"
"""Virtual `NotePageContentDO.page_id` assigned to 1-page standalone image files."""

DEFAULT_IMAGE_EXCLUDE_PATTERNS: tuple[str, ...] = (
    "**/MyStyle/**",
    "**/EXPORT/**",
)
"""Default VFS path globs excluded from standalone image indexing (templates and tablet exports)."""

DEFAULT_MAX_IMAGE_DIMENSION: int = 1568
"""Default longest-edge pixel cap matching common vision-model tile boundaries."""

MIN_ALLOWED_IMAGE_DIMENSION: int = 64
"""Minimum longest-edge pixel cap accepted from external callers."""

MAX_ALLOWED_IMAGE_DIMENSION: int = 2048
"""Maximum longest-edge pixel cap accepted from external callers."""

MAX_SOURCE_IMAGE_BYTES: int = 20 * 1024 * 1024
"""Maximum standalone image size (20 MiB) read into memory for normalization."""

_EXIF_ORIENTATION_TAG = 274
_PNG_COMPRESS_LEVEL = 6


def is_image_filename(file_name: str) -> bool:
    """Return True when ``file_name`` has a supported standalone image extension."""
    return Path(file_name).suffix.lower() in _SUPPORTED_IMAGE_EXTENSIONS


def is_processable_filename(file_name: str) -> bool:
    """Return True when ``file_name`` is a `.note` notebook or supported standalone image."""
    return file_name.lower().endswith(".note") or is_image_filename(file_name)


def _matches_vfs_glob(normalized_path: str, pattern: str) -> bool:
    """Match a lowercase slash-normalized VFS path against a case-insensitive glob pattern."""
    cleaned_pattern = pattern.strip().lstrip("/").lower()
    if not cleaned_pattern:
        return False
    return PurePosixPath(normalized_path).full_match(cleaned_pattern)


def is_indexable_image_path(
    vfs_path: str,
    *,
    enabled: bool = True,
    include_patterns: Sequence[str] = (),
    exclude_patterns: Sequence[str] = DEFAULT_IMAGE_EXCLUDE_PATTERNS,
) -> bool:
    """Return True when a standalone image at ``vfs_path`` should enter the OCR pipeline."""
    if not enabled:
        return False
    normalized = vfs_path.replace("\\", "/").strip().lstrip("/")
    if not normalized or not is_image_filename(normalized):
        return False
    lower_path = normalized.lower()
    if include_patterns and not any(
        _matches_vfs_glob(lower_path, pat) for pat in include_patterns
    ):
        return False
    if any(_matches_vfs_glob(lower_path, pat) for pat in exclude_patterns):
        return False
    return True


def _needs_exif_transpose(img: Image.Image) -> bool:
    """Return True when the image carries a non-identity EXIF orientation tag."""
    orientation = img.getexif().get(_EXIF_ORIENTATION_TAG, 1)
    return orientation != 1


def normalize_image_to_png(
    image_bytes: bytes,
    *,
    max_dimension: int = DEFAULT_MAX_IMAGE_DIMENSION,
) -> tuple[bytes, int, int]:
    """Decode ``image_bytes``, apply EXIF orientation, downscale if needed, and encode as PNG.

    Returns ``(png_bytes, width, height)``. When the input is already a PNG within
    ``max_dimension`` and carries no non-identity EXIF orientation, the original
    bytes are returned without re-encoding.

    Raises:
        ValueError: If ``max_dimension`` is out of bounds or ``image_bytes`` cannot
            be decoded safely.
    """
    if (
        max_dimension < MIN_ALLOWED_IMAGE_DIMENSION
        or max_dimension > MAX_ALLOWED_IMAGE_DIMENSION
    ):
        raise ValueError(
            f"max_dimension must be between {MIN_ALLOWED_IMAGE_DIMENSION} "
            f"and {MAX_ALLOWED_IMAGE_DIMENSION}, got {max_dimension}"
        )

    if not image_bytes:
        raise ValueError("Image data is empty")

    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            img_format = (opened.format or "").upper()
            needs_transpose = _needs_exif_transpose(opened)
            width, height = opened.size

            if (
                img_format == "PNG"
                and not needs_transpose
                and max(width, height) <= max_dimension
            ):
                # Force full decode so truncated/corrupt PNGs are rejected even on pass-through.
                opened.load()
                return image_bytes, width, height

            img = ImageOps.exif_transpose(opened)
            if img is opened:
                img = opened.copy()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as err:
        raise ValueError(f"Invalid or unsupported image data: {err}") from err

    if max(img.size) > max_dimension:
        img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

    if img.mode not in ("RGB", "RGBA", "L", "LA"):
        img = img.convert("RGBA" if "transparency" in img.info else "RGB")

    out = io.BytesIO()
    img.save(out, format="PNG", compress_level=_PNG_COMPRESS_LEVEL)
    final_width, final_height = img.size
    return out.getvalue(), final_width, final_height
