"""Binary bitmap and template encoders for Supernote `.note` layers.

Overview & Design Philosophy
----------------------------
Supernote `.note` files store per-layer raster bitmaps (`BGLAYER`, `MAINLAYER`, and
`LAYER1`–`LAYER3`) alongside optional on-device vector stroke paths (`TOTALPATH`).
While `TOTALPATH` uses a proprietary device-specific stroke format, Supernote firmware
and all `supernote.notebook` converters render page layers directly from their raster
layer bitmaps when `TOTALPATH` is empty (`"0"`).

This module isolates the low-level binary compression protocols from typography, layout,
or notebook metadata concerns:

1. **Foreground & Built-In Paper Layers (`RATTA_RLE`)**:
   - `RattaRleEncoder`: Classic X-series 4-shade + transparent run-length encoding.
   - `RattaRleX2Encoder`: Modern X2-series (`SN_FILE_VER_20230015+`) encoder supporting
     both the 4-shade palette and `highres_grayscale=True` (~240-shade anti-aliased e-ink
     grayscale that sidesteps reserved RLE palette opcodes).
2. **Custom Background Templates (`PNG`)**:
   - `PngEncoder`: Formats custom `BGLAYER` stationery templates to exact device page
     dimensions (`1404x1872` Nomad / `1920x2560` Manta) and computes the `PAGESTYLEMD5`
     digest expected by `user_<name>` page styles.

Transparency & Anti-Aliasing Model
----------------------------------
Supernote layers distinguish between **transparent background** (`color.TRANSPARENT` =
`0xFF`, RLE code `0x62`) and **opaque white ink/card fill** (`color.WHITE` = `0xFE`,
RLE code `0x65`):

- On `MAINLAYER`, `white_is_transparent=True` maps paper-white regions to `0x62` so the
  underlying `BGLAYER` dot-grid or ruled lines remain visible beneath strokes.
- On overlay layers (`LAYER1`–`LAYER3`), `white_is_transparent=False` preserves `0x62`
  outside cards (where RGBA `alpha == 0`) while encoding card interiors as opaque `0x65`
  white so floating cards cleanly mask background dots underneath them.
- Semi-transparent RGBA glyph edges produced by FreeType (`0 < alpha < 255`) are
  premultiplied over white (`255`) prior to quantization so curved strokes encode with
  smooth grayscale anti-aliasing rather than jagged binary thresholds.
"""

from __future__ import annotations

import hashlib
from io import BytesIO

import numpy as np
from PIL import Image

from . import color, exceptions
from .decoder import RattaRleDecoder, RattaRleX2Decoder


class BaseEncoder:
    """Abstract bitmap encoder class."""

    def encode(
        self,
        image: Image.Image,
        *,
        white_is_transparent: bool = False,
    ) -> bytes:
        """Compress a PIL image into layer bitmap bytes."""
        raise NotImplementedError("subclasses must implement encode method")


class RattaRleEncoder(BaseEncoder):
    """Run-length encoder for the X-series `RATTA_RLE` layer bitmap protocol.

    Framing Rules
    -------------
    Each run consists of `(colorcode, length_byte)` pairs scanning row-major across
    `(width, height)` pixels:

    - **1..128 pixels**: `[code, count - 1]` (2 bytes).
    - **129..16,383 pixels**: `[code, 0x80 | (((count - 1) >> 7) - 1), code, (count - 1) & 0x7F]`
      (4 bytes using the high-bit continuation marker).
    - **16,384-pixel chunks**: `[code, 0xFF]` (`SPECIAL_LENGTH_MARKER`), emitted
      repeatedly until the remaining count is `< 16,384`.
    """

    COLORCODE_BLACK = RattaRleDecoder.COLORCODE_BLACK
    COLORCODE_BACKGROUND = RattaRleDecoder.COLORCODE_BACKGROUND
    COLORCODE_DARK_GRAY = RattaRleDecoder.COLORCODE_DARK_GRAY
    COLORCODE_GRAY = RattaRleDecoder.COLORCODE_GRAY
    COLORCODE_WHITE = RattaRleDecoder.COLORCODE_WHITE

    SPECIAL_LENGTH_MARKER = RattaRleDecoder.SPECIAL_LENGTH_MARKER
    SPECIAL_LENGTH = RattaRleDecoder.SPECIAL_LENGTH

    def _build_quantization_lut(self, *, white_is_transparent: bool) -> np.ndarray:
        """Build a 256-entry uint8 lookup table mapping luminance (0..255) to RLE color codes."""
        lut = np.empty(256, dtype=np.uint8)
        lut[0:79] = self.COLORCODE_BLACK
        lut[79:179] = self.COLORCODE_DARK_GRAY
        lut[179:228] = self.COLORCODE_GRAY
        near_white_code = (
            self.COLORCODE_BACKGROUND if white_is_transparent else self.COLORCODE_WHITE
        )
        lut[228:255] = near_white_code
        lut[color.TRANSPARENT] = self.COLORCODE_BACKGROUND
        return lut

    def _image_to_codes(
        self,
        image: Image.Image,
        *,
        white_is_transparent: bool,
    ) -> np.ndarray:
        """Convert a PIL image into a flat 1D numpy array of RATTA_RLE color codes."""
        width, height = image.size
        if width <= 0 or height <= 0:
            raise exceptions.DecoderException(
                f"invalid image dimensions for RLE encoding: ({width}, {height})"
            )

        lut = self._build_quantization_lut(white_is_transparent=white_is_transparent)

        if image.mode in ("RGBA", "LA") or (
            image.mode == "P" and "transparency" in image.info
        ):
            rgba = image.convert("RGBA")
            arr = np.asarray(rgba, dtype=np.uint8)
            alpha = arr[:, :, 3]
            raw_lum = np.asarray(rgba.convert("L"), dtype=np.uint16)
            alpha_u16 = alpha.astype(np.uint16)
            # Blend semi-transparent anti-aliased glyph edges over white paper (255)
            # so FreeType alpha coverage becomes smooth grayscale rather than jagged black.
            blended_lum = (
                (raw_lum * alpha_u16 + 255 * (255 - alpha_u16) + 127) // 255
            ).astype(np.uint8)
            codes = lut[blended_lum]
            if not white_is_transparent:
                opaque_pure_white = (alpha >= 240) & (blended_lum >= 254)
                codes[opaque_pure_white] = self.COLORCODE_WHITE
            codes[alpha < 20] = self.COLORCODE_BACKGROUND
            return codes.ravel()

        if image.mode == "L":
            lum = np.asarray(image, dtype=np.uint8)
            return lut[lum].ravel()

        if image.mode == "RGB":
            rgb = np.asarray(image, dtype=np.uint8)
            lum = np.asarray(image.convert("L"), dtype=np.uint8)
            codes = lut[lum]
            # Pure (255, 255, 255) corresponds to color.RGB_TRANSPARENT -> background (0x62)
            pure_bg = (
                (rgb[:, :, 0] == 255) & (rgb[:, :, 1] == 255) & (rgb[:, :, 2] == 255)
            )
            codes[pure_bg] = self.COLORCODE_BACKGROUND
            return codes.ravel()

        lum = np.asarray(image.convert("L"), dtype=np.uint8)
        return lut[lum].ravel()

    @classmethod
    def _encode_codes(cls, codes: np.ndarray) -> bytes:
        """Run-length encode a 1D uint8 array of color codes using RATTA_RLE framing."""
        if codes.size == 0:
            return b""

        diffs = np.flatnonzero(codes[1:] != codes[:-1]) + 1
        starts = np.empty(diffs.size + 1, dtype=np.int64)
        starts[0] = 0
        starts[1:] = diffs

        ends = np.empty(diffs.size + 1, dtype=np.int64)
        ends[:-1] = diffs
        ends[-1] = codes.size

        lengths = ends - starts
        run_codes = codes[starts]

        out = bytearray()
        special_len = cls.SPECIAL_LENGTH
        special_marker = cls.SPECIAL_LENGTH_MARKER

        for code_val, count_val in zip(
            run_codes.tolist(), lengths.tolist(), strict=True
        ):
            code = int(code_val)
            count = int(count_val)

            while count >= special_len:
                out.append(code)
                out.append(special_marker)
                count -= special_len

            if count > 128:
                rem = count - 1
                hi = (rem >> 7) - 1
                lo = rem & 0x7F
                out.append(code)
                out.append(0x80 | hi)
                out.append(code)
                out.append(lo)
            elif count > 0:
                out.append(code)
                out.append(count - 1)

        return bytes(out)

    def encode(
        self,
        image: Image.Image,
        *,
        white_is_transparent: bool = False,
    ) -> bytes:
        """Encode a PIL image into `RATTA_RLE` compressed layer bytes.

        Args:
            image: Source PIL image (`L`, `RGB`, `RGBA`, `LA`, or `P`).
            white_is_transparent: When `True`, near-white pixels collapse to
                `COLORCODE_BACKGROUND` (`0x62`) so lower layers show through. When
                `False`, opaque white pixels encode as `COLORCODE_WHITE` (`0x65`) while
                transparent RGBA pixels (`alpha < 20`) still map to `0x62`.
        """
        codes = self._image_to_codes(image, white_is_transparent=white_is_transparent)
        return self._encode_codes(codes)


class RattaRleX2Encoder(RattaRleEncoder):
    """`RATTA_RLE` encoder for X2-series notebooks (`SN_FILE_VER_20230015` and newer).

    When `highres_grayscale=True`, non-reserved byte values (`1..253` excluding `0x61`–`0x68`,
    `0x9E`, and `0xCA`) decode directly to their 8-bit grayscale luminance in
    `RattaRleX2Decoder`. Reserved opcode bytes are remapped to the nearest adjacent
    luminance (+/- 1..4 levels), enabling smooth anti-aliased typography, variable-weight
    pen strokes, and soft highlighter washes on `MAINLAYER` and `LAYER1`–`LAYER3`.
    """

    COLORCODE_DARK_GRAY = RattaRleX2Decoder.COLORCODE_DARK_GRAY
    COLORCODE_GRAY = RattaRleX2Decoder.COLORCODE_GRAY

    def __init__(self, *, highres_grayscale: bool = False) -> None:
        self.highres_grayscale = highres_grayscale

    def _build_quantization_lut(self, *, white_is_transparent: bool) -> np.ndarray:
        if not self.highres_grayscale:
            return super()._build_quantization_lut(
                white_is_transparent=white_is_transparent
            )

        # In X2 high-res grayscale, non-reserved byte values decode directly to their
        # 8-bit grayscale luminance. Remap reserved opcode bytes to nearest safe shade.
        lut = np.arange(256, dtype=np.uint8)
        lut[0] = self.COLORCODE_BLACK
        # 0x61..0x64 (97..100) -> 0x60 (96); 0x65..0x68 (101..104) -> 0x69 (105)
        lut[0x61:0x65] = 0x60
        lut[0x65:0x69] = 0x69
        # 0x9E -> 0x9D (COLORCODE_DARK_GRAY = 157); 0xCA -> 0xC9 (COLORCODE_GRAY = 201)
        lut[0x9E] = self.COLORCODE_DARK_GRAY
        lut[0xCA] = self.COLORCODE_GRAY
        lut[color.WHITE] = (
            self.COLORCODE_BACKGROUND if white_is_transparent else self.COLORCODE_WHITE
        )
        lut[color.TRANSPARENT] = self.COLORCODE_BACKGROUND
        if white_is_transparent:
            lut[245:256] = self.COLORCODE_BACKGROUND
        return lut


class PngEncoder:
    """Encoder for custom `user_<style>` PNG background templates on `BGLAYER`.

    Supernote notebooks allow `BGLAYER` to store a standard PNG image whenever the page's
    `PAGESTYLE` begins with `"user_"` and `PAGESTYLEMD5` matches the MD5 hex digest of
    the encoded PNG payload (even though the layer metadata still declares
    `LAYERPROTOCOL = "RATTA_RLE"`).
    """

    def encode_with_md5(
        self,
        image: Image.Image,
        page_width: int,
        page_height: int,
    ) -> tuple[bytes, str]:
        """Format an image to exact `(page_width, page_height)` PNG bytes and return `(png_bytes, md5_hex)`."""
        if page_width <= 0 or page_height <= 0:
            raise exceptions.DecoderException(
                f"invalid target PNG dimensions: {(page_width, page_height)}"
            )
        if image.size != (page_width, page_height):
            canvas = Image.new("RGBA", (page_width, page_height), (255, 255, 255, 255))
            resized = image.copy()
            resized.thumbnail((page_width, page_height), Image.Resampling.LANCZOS)
            offset_x = (page_width - resized.width) // 2
            offset_y = (page_height - resized.height) // 2
            if resized.mode in ("RGBA", "LA"):
                rgba = resized.convert("RGBA")
                canvas.paste(rgba, (offset_x, offset_y), rgba)
            else:
                canvas.paste(resized.convert("RGB"), (offset_x, offset_y))
            target = canvas
        else:
            target = image

        buf = BytesIO()
        target.save(buf, format="PNG", optimize=False)
        png_bytes = buf.getvalue()
        md5_hex = hashlib.md5(png_bytes).hexdigest()
        return png_bytes, md5_hex
