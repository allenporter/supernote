import base64
import io
import json
import zlib

import numpy as np
import pytest
from PIL import Image

from supernote.notebook import color, decoder, exceptions


@pytest.fixture
def rgb_palette() -> color.ColorPalette:
    return color.ColorPalette(
        color.MODE_RGB,
        (color.RGB_BLACK, color.RGB_DARK_GRAY, color.RGB_GRAY, color.RGB_WHITE),
    )


@pytest.fixture
def flate_payload() -> bytes:
    flate_decoder = decoder.FlateDecoder()
    arr = np.full(
        (flate_decoder.INTERNAL_PAGE_WIDTH, flate_decoder.INTERNAL_PAGE_HEIGHT),
        flate_decoder.COLORCODE_BACKGROUND,
        dtype=np.uint16,
    )
    arr[0, 0] = flate_decoder.COLORCODE_BLACK
    arr[0, 1] = flate_decoder.COLORCODE_DARK_GRAY
    arr[0, 2] = flate_decoder.COLORCODE_GRAY
    return zlib.compress(arr.tobytes())


@pytest.fixture
def sample_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 3), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def test_base_decoder_raises_not_implemented() -> None:
    base = decoder.BaseDecoder()
    with pytest.raises(NotImplementedError):
        base.decode(b"", 10, 10)


def test_flate_decoder_grayscale(flate_payload: bytes) -> None:
    flate_decoder = decoder.FlateDecoder()
    bitmap, size, bpp = flate_decoder.decode(flate_payload, 1404, 1872)
    assert size == (1404, 1872)
    assert bpp == 8
    assert len(bitmap) == 1404 * 1872


def test_flate_decoder_rgb(
    flate_payload: bytes, rgb_palette: color.ColorPalette
) -> None:
    flate_decoder = decoder.FlateDecoder()
    bitmap, size, bpp = flate_decoder.decode(
        flate_payload, 1404, 1872, palette=rgb_palette
    )
    assert size == (1404, 1872)
    assert bpp == 32
    assert len(bitmap) == 1404 * 1872 * 4


def test_flate_decoder_rejects_corrupt_zlib_stream() -> None:
    flate_decoder = decoder.FlateDecoder()
    with pytest.raises(exceptions.DecoderException, match="failed to decompress"):
        flate_decoder.decode(b"not-valid-zlib", 1404, 1872)


def test_flate_decoder_rejects_wrong_uncompressed_length() -> None:
    flate_decoder = decoder.FlateDecoder()
    short_compressed = zlib.compress(b"\x00" * 32)
    with pytest.raises(exceptions.DecoderException, match="uncompressed bitmap length"):
        flate_decoder.decode(short_compressed, 1404, 1872)


def test_ratta_rle_decoder_grayscale() -> None:
    rle = decoder.RattaRleDecoder()
    payload = bytes([rle.COLORCODE_BLACK, 1, rle.COLORCODE_WHITE, 1])
    bitmap, size, bpp = rle.decode(payload, 2, 2)
    assert size == (2, 2)
    assert bpp == 8
    assert bitmap == bytes(
        [
            color.DEFAULT_COLORPALETTE.black,
            color.DEFAULT_COLORPALETTE.black,
            color.DEFAULT_COLORPALETTE.white,
            color.DEFAULT_COLORPALETTE.white,
        ]
    )


def test_ratta_rle_decoder_rgb_horizontal(rgb_palette: color.ColorPalette) -> None:
    rle = decoder.RattaRleDecoder()
    payload = bytes([rle.COLORCODE_BLACK, 1, rle.COLORCODE_WHITE, 1])
    bitmap, size, bpp = rle.decode(payload, 1, 4, palette=rgb_palette, horizontal=True)
    assert size == (4, 1)
    assert bpp == 24
    assert len(bitmap) == 12


def test_ratta_rle_decoder_special_blank_marker() -> None:
    rle = decoder.RattaRleDecoder()
    payload = bytes([rle.COLORCODE_BACKGROUND, rle.SPECIAL_LENGTH_MARKER])
    bitmap, size, bpp = rle.decode(payload, 32, 32, all_blank=True)
    assert size == (32, 32)
    assert bpp == 8
    assert len(bitmap) == 1024


def test_ratta_rle_x2_decoder_palette_mapping() -> None:
    rle_x2 = decoder.RattaRleX2Decoder()
    payload = bytes(
        [
            rle_x2.COLORCODE_DARK_GRAY,
            0,
            rle_x2.COLORCODE_GRAY_COMPAT,
            0,
        ]
    )
    bitmap, size, bpp = rle_x2.decode(payload, 2, 1)
    assert size == (2, 1)
    assert bpp == 8
    assert bitmap == bytes(
        [
            color.DEFAULT_COLORPALETTE.darkgray,
            color.DEFAULT_COLORPALETTE.gray_compat,
        ]
    )


def test_ratta_rle_decoder_high_bit_holder_merges_same_color() -> None:
    rle = decoder.RattaRleDecoder()
    # 0x80 held + same color length 2 => 1 + 2 + ((0 + 1) << 7) = 131 pixels
    payload = bytes([rle.COLORCODE_BLACK, 0x80, rle.COLORCODE_BLACK, 2])
    bitmap, size, _ = rle.decode(payload, 131, 1)
    assert size == (131, 1)
    assert len(bitmap) == 131


def test_ratta_rle_decoder_high_bit_holder_flushes_on_color_change() -> None:
    rle = decoder.RattaRleDecoder()
    # 0x80 held (128 pixels) followed by a different color of 1 pixel => 129 pixels
    payload = bytes([rle.COLORCODE_BLACK, 0x80, rle.COLORCODE_WHITE, 0])
    bitmap, size, _ = rle.decode(payload, 129, 1)
    assert size == (129, 1)
    assert len(bitmap) == 129


def test_ratta_rle_decoder_adjusts_trailing_holder_at_eof() -> None:
    rle = decoder.RattaRleDecoder()
    # Trailing high-bit holder adjusted at EOF (gap = 64 => ((0 & 0x7F) + 1) << 6 = 64)
    payload = bytes([rle.COLORCODE_BLACK, 0x80])
    bitmap, size, _ = rle.decode(payload, 64, 1)
    assert size == (64, 1)
    assert len(bitmap) == 64


@pytest.mark.parametrize("run_length", [10, 0], ids=["overflow", "underflow"])
def test_ratta_rle_decoder_rejects_mismatched_bitmap_length(run_length: int) -> None:
    rle = decoder.RattaRleDecoder()
    with pytest.raises(exceptions.DecoderException, match="uncompressed bitmap length"):
        rle.decode(bytes([rle.COLORCODE_BLACK, run_length]), 2, 2)


def test_png_decoder_rgba(sample_png_bytes: bytes) -> None:
    png_decoder = decoder.PngDecoder()
    bitmap, size, bpp = png_decoder.decode(sample_png_bytes, 4, 3)
    assert size == (4, 3)
    assert bpp == 32
    assert len(bitmap) == 4 * 3 * 4


def test_png_decoder_rejects_mismatched_dimensions(sample_png_bytes: bytes) -> None:
    png_decoder = decoder.PngDecoder()
    with pytest.raises(exceptions.DecoderException, match="invalid size"):
        png_decoder.decode(sample_png_bytes, 5, 3)


def test_text_decoder_returns_none_for_none_input() -> None:
    text_decoder = decoder.TextDecoder()
    assert text_decoder.decode(None) is None


def test_text_decoder_returns_none_for_empty_elements() -> None:
    text_decoder = decoder.TextDecoder()
    empty_b64 = base64.b64encode(json.dumps({"elements": []}).encode("utf-8"))
    assert text_decoder.decode(empty_b64) is None


def test_text_decoder_ignores_non_text_and_blank_elements() -> None:
    text_decoder = decoder.TextDecoder()
    payload = {
        "elements": [
            {"type": "Raw Content", "label": "ignored"},
            {"type": "Text", "label": ""},
        ]
    }
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8"))
    assert text_decoder.decode(encoded) is None


def test_text_decoder_extracts_text_elements_with_vertical_positions() -> None:
    text_decoder = decoder.TextDecoder()
    payload = {
        "elements": [
            {
                "type": "Text",
                "label": "First line",
                "words": [{}, {"bounding-box": {"y": 42}}],
            },
            {"type": "Text", "label": "No bbox"},
        ]
    }
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8"))
    assert text_decoder.decode(encoded) == [
        decoder.TextElement(label="First line", y=42),
        decoder.TextElement(label="No bbox", y=0),
    ]
