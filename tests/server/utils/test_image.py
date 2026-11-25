"""Unit tests for `supernote.server.utils.image`."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from supernote.server.utils.image import (
    MAX_ALLOWED_IMAGE_DIMENSION,
    MIN_ALLOWED_IMAGE_DIMENSION,
    is_image_filename,
    normalize_image_to_png,
)


def _make_image_bytes(
    size: tuple[int, int],
    *,
    fmt: str = "PNG",
    mode: str = "RGB",
    exif_orientation: int | None = None,
) -> bytes:
    img = Image.new(mode, size, color=128 if mode == "L" else (10, 20, 30))
    buf = io.BytesIO()
    save_kwargs: dict[str, object] = {}
    if exif_orientation is not None:
        exif = img.getexif()
        exif[274] = exif_orientation
        save_kwargs["exif"] = exif.tobytes()
    img.save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("photo.png", True),
        ("photo.PNG", True),
        ("scan.jpg", True),
        ("scan.JPEG", True),
        ("anim.gif", True),
        ("diagram.webp", True),
        ("bitmap.bmp", True),
        ("vector.svg", False),
        ("notebook.note", False),
        ("doc.pdf", False),
        ("readme.txt", False),
        ("no_extension", False),
    ],
)
def test_is_image_filename(file_name: str, expected: bool) -> None:
    assert is_image_filename(file_name) is expected


def test_normalize_image_to_png_passthrough_for_small_png() -> None:
    raw = _make_image_bytes((320, 240), fmt="PNG")
    out, width, height = normalize_image_to_png(raw, max_dimension=512)
    assert out == raw
    assert (width, height) == (320, 240)


def test_normalize_image_to_png_downscales_preserving_aspect_ratio() -> None:
    raw = _make_image_bytes((2000, 1000), fmt="PNG")
    out, width, height = normalize_image_to_png(raw, max_dimension=500)
    assert (width, height) == (500, 250)
    with Image.open(io.BytesIO(out)) as decoded:
        assert decoded.format == "PNG"
        assert decoded.size == (500, 250)


@pytest.mark.parametrize("fmt", ["JPEG", "WEBP"])
def test_normalize_image_to_png_converts_non_png_formats(fmt: str) -> None:
    raw = _make_image_bytes((400, 300), fmt=fmt)
    out, width, height = normalize_image_to_png(raw, max_dimension=1024)
    assert (width, height) == (400, 300)
    with Image.open(io.BytesIO(out)) as decoded:
        assert decoded.format == "PNG"
        assert decoded.size == (400, 300)


def test_normalize_image_to_png_applies_exif_orientation() -> None:
    # Orientation 6 rotates 90 degrees clockwise, swapping width and height.
    raw = _make_image_bytes((400, 200), fmt="JPEG", exif_orientation=6)
    out, width, height = normalize_image_to_png(raw, max_dimension=1024)
    assert (width, height) == (200, 400)
    with Image.open(io.BytesIO(out)) as decoded:
        assert decoded.size == (200, 400)


def test_normalize_image_to_png_converts_cmyk_mode() -> None:
    img = Image.new("CMYK", (120, 80), color=(0, 0, 0, 100))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    out, width, height = normalize_image_to_png(buf.getvalue(), max_dimension=512)
    assert (width, height) == (120, 80)
    with Image.open(io.BytesIO(out)) as decoded:
        assert decoded.format == "PNG"
        assert decoded.mode == "RGB"


@pytest.mark.parametrize(
    "bad_dimension",
    [MIN_ALLOWED_IMAGE_DIMENSION - 1, 0, -10, MAX_ALLOWED_IMAGE_DIMENSION + 1],
)
def test_normalize_image_to_png_rejects_out_of_bounds_dimension(
    bad_dimension: int,
) -> None:
    raw = _make_image_bytes((100, 100))
    with pytest.raises(ValueError, match="max_dimension"):
        normalize_image_to_png(raw, max_dimension=bad_dimension)


@pytest.mark.parametrize(
    "bad_bytes",
    [b"", b"not an image", _make_image_bytes((200, 200))[:24]],
)
def test_normalize_image_to_png_rejects_invalid_or_truncated_bytes(
    bad_bytes: bytes,
) -> None:
    with pytest.raises(ValueError):
        normalize_image_to_png(bad_bytes)
