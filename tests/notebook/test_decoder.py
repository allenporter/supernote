import base64
import io
import json
import zlib

import numpy as np
import pytest
from PIL import Image

from supernote.notebook import color, exceptions, fileformat
from supernote.notebook.decoder import (
    BaseDecoder,
    FlateDecoder,
    PngDecoder,
    RattaRleDecoder,
    RattaRleX2Decoder,
    TextDecoder,
    TextElement,
)


def test_base_decoder_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        BaseDecoder().decode(b"data")


def test_flate_decoder_grayscale_and_rgb_and_error_paths() -> None:
    decoder = FlateDecoder()
    total_pixels = FlateDecoder.INTERNAL_PAGE_WIDTH * FlateDecoder.INTERNAL_PAGE_HEIGHT
    expected_bytes = total_pixels * np.dtype(np.uint16).itemsize

    arr = np.full(total_pixels, FlateDecoder.COLORCODE_BACKGROUND, dtype=np.uint16)
    arr[0] = FlateDecoder.COLORCODE_BLACK
    arr[1] = FlateDecoder.COLORCODE_DARK_GRAY
    arr[2] = FlateDecoder.COLORCODE_GRAY
    valid_payload = zlib.compress(arr.tobytes())

    bitmap, size, bpp = decoder.decode(
        valid_payload, fileformat.PAGE_WIDTH, fileformat.PAGE_HEIGHT
    )
    assert size == (fileformat.PAGE_WIDTH, fileformat.PAGE_HEIGHT)
    assert bpp == 8
    assert len(bitmap) == fileformat.PAGE_WIDTH * fileformat.PAGE_HEIGHT

    rgb_bitmap, rgb_size, rgb_bpp = decoder.decode(
        valid_payload,
        fileformat.PAGE_WIDTH,
        fileformat.PAGE_HEIGHT,
        palette=color.DEFAULT_RGB_COLORPALETTE,
    )
    assert rgb_size == (fileformat.PAGE_WIDTH, fileformat.PAGE_HEIGHT)
    assert rgb_bpp == 32
    assert len(rgb_bitmap) == fileformat.PAGE_WIDTH * fileformat.PAGE_HEIGHT * 4

    # Zlib bomb expanding well beyond expected_bytes is rejected at expected_bytes + 1
    bomb_payload = zlib.compress(b"\x00" * (expected_bytes * 4))
    with pytest.raises(exceptions.DecoderException, match="uncompressed bitmap length"):
        decoder.decode(bomb_payload, fileformat.PAGE_WIDTH, fileformat.PAGE_HEIGHT)

    # Truncated uncompressed payload is rejected
    short_payload = zlib.compress(b"\x00" * 128)
    with pytest.raises(exceptions.DecoderException, match="uncompressed bitmap length"):
        decoder.decode(short_payload, fileformat.PAGE_WIDTH, fileformat.PAGE_HEIGHT)

    # Corrupt zlib stream raises DecoderException
    with pytest.raises(
        exceptions.DecoderException, match="failed to decompress bitmap"
    ):
        decoder.decode(b"not-valid-zlib", fileformat.PAGE_WIDTH, fileformat.PAGE_HEIGHT)


def test_ratta_rle_decoder_modes_and_error_paths() -> None:
    decoder = RattaRleDecoder()

    # Repeat 0x4000-pixel runs well past a 10x10 page (100 bytes expected)
    bomb_rle = (
        bytes([RattaRleDecoder.COLORCODE_BLACK, RattaRleDecoder.SPECIAL_LENGTH_MARKER])
        * 50
    )
    with pytest.raises(exceptions.DecoderException, match="uncompressed bitmap length"):
        decoder.decode(bomb_rle, page_width=10, page_height=10)

    # Truncated RLE stream (only 2 pixels for a 4x4 page)
    short_rle = bytes([RattaRleDecoder.COLORCODE_BLACK, 1])
    with pytest.raises(exceptions.DecoderException, match="uncompressed bitmap length"):
        decoder.decode(short_rle, page_width=4, page_height=4)

    # all_blank=True with SPECIAL_LENGTH_MARKER produces SPECIAL_LENGTH_FOR_BLANK (0x400 = 1024) pixels
    blank_rle = bytes(
        [RattaRleDecoder.COLORCODE_BACKGROUND, RattaRleDecoder.SPECIAL_LENGTH_MARKER]
    )
    bitmap, size, bpp = decoder.decode(
        blank_rle,
        page_width=32,
        page_height=32,
        palette=color.DEFAULT_RGB_COLORPALETTE,
        all_blank=True,
    )
    assert size == (32, 32)
    assert bpp == 24
    assert len(bitmap) == 32 * 32 * 3

    # X2 decoder colormap includes compatibility grayscale codes
    x2_decoder = RattaRleX2Decoder()
    x2_rle = bytes([RattaRleX2Decoder.COLORCODE_DARK_GRAY_COMPAT, 3])
    x2_bitmap, x2_size, x2_bpp = x2_decoder.decode(x2_rle, page_width=2, page_height=2)
    assert x2_size == (2, 2)
    assert x2_bpp == 8
    assert x2_bitmap == bytes([color.DARK_GRAY_COMPAT] * 4)


def test_png_decoder_valid_and_size_mismatch() -> None:
    decoder = PngDecoder()
    buf = io.BytesIO()
    Image.new("RGBA", (4, 4), (10, 20, 30, 255)).save(buf, format="PNG")
    png_bytes = buf.getvalue()

    bitmap, size, bpp = decoder.decode(png_bytes, page_width=4, page_height=4)
    assert size == (4, 4)
    assert bpp == 32
    assert len(bitmap) == 4 * 4 * 4

    with pytest.raises(exceptions.DecoderException, match="invalid size"):
        decoder.decode(png_bytes, page_width=8, page_height=8)


def test_text_decoder_elements_and_edge_cases() -> None:
    decoder = TextDecoder()
    assert decoder.decode(None) is None

    empty_payload = base64.b64encode(json.dumps({"elements": []}).encode()).decode()
    assert decoder.decode(empty_payload.encode()) is None

    no_text_payload = base64.b64encode(
        json.dumps(
            {
                "elements": [
                    {"type": "Raw Content"},
                    {"type": "Text", "label": ""},
                ]
            }
        ).encode()
    ).decode()
    assert decoder.decode(no_text_payload.encode()) is None

    valid_payload = base64.b64encode(
        json.dumps(
            {
                "elements": [
                    {
                        "type": "Text",
                        "label": "Line 1",
                        "words": [{"bounding-box": {"y": 42}}],
                    },
                    {
                        "type": "Text",
                        "label": "No bbox word",
                        "words": [{}],
                    },
                ]
            }
        ).encode()
    ).decode()
    assert decoder.decode(valid_payload.encode()) == [
        TextElement(label="Line 1", y=42),
        TextElement(label="No bbox word", y=0),
    ]
