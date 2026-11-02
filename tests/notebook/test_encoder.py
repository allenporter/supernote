"""Round-trip and boundary tests for Supernote bitmap and PNG encoders."""

from __future__ import annotations

from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from supernote.notebook import color, exceptions, fileformat
from supernote.notebook.decoder import PngDecoder, RattaRleDecoder, RattaRleX2Decoder
from supernote.notebook.encoder import PngEncoder, RattaRleEncoder, RattaRleX2Encoder


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (fileformat.PAGE_WIDTH, fileformat.PAGE_HEIGHT),
        (fileformat.A5X2_PAGE_WIDTH, fileformat.A5X2_PAGE_HEIGHT),
    ],
)
def test_ratta_rle_x2_blank_and_patterned_roundtrip(width: int, height: int) -> None:
    encoder = RattaRleX2Encoder()
    decoder = RattaRleX2Decoder()

    # All-transparent page (matches firmware ~324 / ~600 byte compact encoding)
    blank = Image.new("L", (width, height), color=color.TRANSPARENT)
    encoded_blank = encoder.encode(blank)
    assert len(encoded_blank) <= 650
    raw, size, bpp = decoder.decode(encoded_blank, width, height)
    assert size == (width, height)
    assert bpp == 8
    assert raw == blank.tobytes()

    # All 5 canonical Supernote palette values in L mode round-trip losslessly
    arr = np.full((height, width), color.TRANSPARENT, dtype=np.uint8)
    arr[10:60, 20:200] = color.BLACK
    arr[80:140, 50:400] = color.DARK_GRAY
    arr[160:220, 100:500] = color.GRAY
    arr[240:310, 120:600] = color.WHITE
    img = Image.fromarray(arr, mode="L")

    encoded = encoder.encode(img)
    decoded_bytes, dec_size, _ = decoder.decode(encoded, width, height)
    assert dec_size == (width, height)
    decoded_arr = np.frombuffer(decoded_bytes, dtype=np.uint8).reshape((height, width))
    assert np.array_equal(decoded_arr, arr)


def test_ratta_rle_x1_encoder_decoder_roundtrip() -> None:
    w, h = 200, 150
    encoder = RattaRleEncoder()
    decoder = RattaRleDecoder()

    arr = np.full((h, w), color.TRANSPARENT, dtype=np.uint8)
    arr[5:25, 5:50] = color.BLACK
    arr[30:55, 10:80] = color.DARK_GRAY
    arr[60:85, 15:90] = color.GRAY
    arr[90:120, 20:100] = color.WHITE
    img = Image.fromarray(arr, mode="L")

    encoded = encoder.encode(img)
    decoded_bytes, size, bpp = decoder.decode(encoded, w, h)
    assert size == (w, h)
    assert bpp == 8
    assert decoded_bytes == img.tobytes()


@pytest.mark.parametrize(
    "run_len",
    [
        1,
        2,
        127,
        128,
        129,
        130,
        255,
        256,
        257,
        4096,
        16255,
        16256,
        16257,
        16383,
        16384,
        16385,
        32769,
    ],
)
def test_ratta_rle_boundary_run_lengths(run_len: int) -> None:
    """Verify exact framing across single-byte, 0x80-continuation, and 0xFF (16384) boundaries."""
    total_pixels = run_len + 17
    arr = np.full((1, total_pixels), color.TRANSPARENT, dtype=np.uint8)
    arr[0, :run_len] = color.BLACK
    arr[0, run_len:] = color.DARK_GRAY
    img = Image.fromarray(arr, mode="L")

    encoded = RattaRleX2Encoder().encode(img)
    decoded_bytes, size, _ = RattaRleX2Decoder().decode(encoded, total_pixels, 1)
    assert size == (total_pixels, 1)
    assert decoded_bytes == img.tobytes()


def test_ratta_rle_rgba_transparency_and_opaque_white() -> None:
    w, h = 64, 64
    rgba = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    rgba_arr = np.array(rgba, dtype=np.uint8)
    # Opaque pure white card region
    rgba_arr[10:30, 10:30] = (255, 255, 255, 255)
    # Opaque black ink inside card
    rgba_arr[15:20, 15:20] = (0, 0, 0, 255)
    img = Image.fromarray(rgba_arr, mode="RGBA")

    # With white_is_transparent=False, alpha=0 -> TRANSPARENT (0xFF), alpha=255 white -> WHITE (0xFE)
    enc_opaque = RattaRleX2Encoder().encode(img, white_is_transparent=False)
    dec_opaque, _, _ = RattaRleX2Decoder().decode(enc_opaque, w, h)
    dec_arr = np.frombuffer(dec_opaque, dtype=np.uint8).reshape((h, w))
    assert dec_arr[0, 0] == color.TRANSPARENT
    assert dec_arr[12, 12] == color.WHITE
    assert dec_arr[16, 16] == color.BLACK

    # With white_is_transparent=True, opaque white also collapses to TRANSPARENT (0xFF)
    enc_trans = RattaRleX2Encoder().encode(img, white_is_transparent=True)
    dec_trans, _, _ = RattaRleX2Decoder().decode(enc_trans, w, h)
    dec_trans_arr = np.frombuffer(dec_trans, dtype=np.uint8).reshape((h, w))
    assert dec_trans_arr[12, 12] == color.TRANSPARENT
    assert dec_trans_arr[16, 16] == color.BLACK


def test_ratta_rle_x2_highres_grayscale_avoids_reserved_opcodes() -> None:
    w, h = 256, 4
    gradient = np.tile(np.arange(256, dtype=np.uint8), (h, 1))
    img = Image.fromarray(gradient, mode="L")

    encoded = RattaRleX2Encoder(highres_grayscale=True).encode(img)
    decoded_bytes, size, _ = RattaRleX2Decoder().decode(encoded, w, h)
    assert size == (w, h)
    decoded = np.frombuffer(decoded_bytes, dtype=np.uint8).reshape((h, w))[0]
    # Every grayscale value should decode within <= 4 levels of original luminance
    diffs = np.abs(decoded.astype(np.int16) - np.arange(256, dtype=np.int16))
    assert int(diffs.max()) <= 5


def test_ratta_rle_horizontal_decode_compatibility() -> None:
    pw, ph = fileformat.PAGE_WIDTH, fileformat.PAGE_HEIGHT
    # Horizontal page has swapped (ph, pw) canvas
    horiz_img = Image.new("L", (ph, pw), color=color.TRANSPARENT)
    arr = np.array(horiz_img)
    arr[50:100, 100:500] = color.BLACK
    horiz_img = Image.fromarray(arr, mode="L")

    encoded = RattaRleX2Encoder().encode(horiz_img)
    decoded_bytes, size, _ = RattaRleX2Decoder().decode(
        encoded, pw, ph, horizontal=True
    )
    assert size == (ph, pw)
    assert decoded_bytes == horiz_img.tobytes()


def test_ratta_rle_rejects_empty_dimensions() -> None:
    empty_img = Image.new("L", (0, 0))
    with pytest.raises(exceptions.DecoderException, match="invalid image dimensions"):
        RattaRleX2Encoder().encode(empty_img)
    with pytest.raises(
        exceptions.DecoderException, match="invalid target PNG dimensions"
    ):
        PngEncoder().encode_with_md5(Image.new("RGB", (10, 10)), 0, 10)


def test_ratta_rle_semitransparent_alpha_blends_cleanly_and_4shade_quantizes() -> None:
    w, h = 16, 16
    rgba_arr = np.zeros((h, w, 4), dtype=np.uint8)
    # 50% alpha black stroke edge should blend against white (~127 gray), not solid black (0)
    rgba_arr[:, :] = (0, 0, 0, 128)
    img = Image.fromarray(rgba_arr, mode="RGBA")

    enc_highres = RattaRleX2Encoder(highres_grayscale=True).encode(img)
    dec_highres, _, _ = RattaRleX2Decoder().decode(enc_highres, w, h)
    lum = dec_highres[0]
    assert 115 <= lum <= 140

    enc_quant = RattaRleX2Encoder(highres_grayscale=False).encode(img)
    dec_quant, _, _ = RattaRleX2Decoder().decode(enc_quant, w, h)
    assert dec_quant[0] == color.DARK_GRAY


def test_png_encoder_resizes_and_matches_png_decoder() -> None:
    pw, ph = fileformat.PAGE_WIDTH, fileformat.PAGE_HEIGHT
    small = Image.new("RGB", (300, 400), (200, 200, 200))
    png_bytes, md5_hex = PngEncoder().encode_with_md5(small, pw, ph)
    assert len(md5_hex) == 32

    bitmap, size, bpp = PngDecoder().decode(png_bytes, pw, ph)
    assert size == (pw, ph)
    assert bpp == 32
    assert len(bitmap) == pw * ph * 4

    with Image.open(BytesIO(png_bytes)) as reloaded:
        assert reloaded.size == (pw, ph)
