# Copyright (c) 2020 jya
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Page and notebook converters for rendering `.note` files to PNG, SVG, PDF, and text.

This module defines `ImageConverter` (`PngConverter`), `SvgConverter`, `PdfConverter`, and
`TextConverter`, along with layer visibility configuration (`VisibilityOverlay`,
`build_visibility_overlay`). Converters composite decompressed layer bitmaps using
`supernote.notebook.decoder` and `supernote.notebook.color.ColorPalette`, vectorize strokes via
`potrace` for SVG/PDF, or extract realtime handwriting recognition blocks (`RECOGNTEXT`).
See `supernote.notebook` and `supernote.guides.notebook_spec`.
"""

import base64
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from io import BytesIO

import potrace
import svgwrite
from PIL import Image
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from . import color, exceptions, fileformat, schema, utils
from . import decoder as Decoder
from .color import ColorPalette
from .fileformat import Notebook


class VisibilityOverlay(Enum):
    DEFAULT = auto()
    VISIBLE = auto()
    INVISIBLE = auto()


def build_visibility_overlay(
    background=VisibilityOverlay.DEFAULT,
    main=VisibilityOverlay.DEFAULT,
    layer1=VisibilityOverlay.DEFAULT,
    layer2=VisibilityOverlay.DEFAULT,
    layer3=VisibilityOverlay.DEFAULT,
):
    return {
        "BGLAYER": background,
        "MAINLAYER": main,
        "LAYER1": layer1,
        "LAYER2": layer2,
        "LAYER3": layer3,
    }


_NON_TRANSPARENT_LUT = [0 if x == color.TRANSPARENT else 1 for x in range(256)]
_TRANSPARENT_LUT = [1 if x == color.TRANSPARENT else 0 for x in range(256)]


class ImageConverter:
    SPECIAL_WHITE_STYLE_BLOCK_SIZE = 0x140E

    def __init__(self, notebook, palette=None):
        self.note = notebook
        self.palette = palette

    def convert(self, page_number, visibility_overlay=None):
        """Returns an image of the given page.

        Parameters
        ----------
        page_number : int
            page number to convert

        Returns
        -------
        PIL.Image.Image
            an image object
        """
        page = self.note.page(page_number)
        if page.is_layer_supported():
            highres_grayscale = self.note.supports_highres_grayscale()
            converted_img = self._convert_layered_page(
                page, self.palette, visibility_overlay, highres_grayscale
            )
        else:
            converted_img = self._convert_nonlayered_page(
                page, self.palette, visibility_overlay
            )
        if (
            visibility_overlay is not None
            and visibility_overlay.get("BGLAYER") == VisibilityOverlay.INVISIBLE
        ):
            converted_img = self._make_transparent(converted_img)
        return converted_img

    def convert_title(self, title: fileformat.Title) -> Image.Image:
        """Decode a notebook `Title`'s `<TITLEBITMAP>` into a cropped image.

        Supports both modern cropped title bitmaps (sized to `<TITLERECT>`) and
        legacy full-page title bitmaps (decoded at page dimensions and cropped
        to `<TITLERECT>`).
        """
        if not title.content:
            raise exceptions.DecoderException("title has no bitmap content")
        rect = title.metadata.rect or title.metadata.rect_original
        if rect is None:
            raise exceptions.DecoderException("title has no TITLERECT")

        horizontal = self.note.pages[title.page_number].is_horizontal()
        page_width, page_height = self.note.width, self.note.height
        if horizontal:
            page_width, page_height = page_height, page_width
        # TITLERECT is untrusted file input and sets the decode buffer size, so
        # bounding it by the page caps memory (a few KB of RLE can otherwise
        # expand to hundreds of MB) and keeps crops from padding off-page.
        if not (
            rect.width > 0
            and rect.height > 0
            and rect.left >= 0
            and rect.top >= 0
            and rect.right <= page_width
            and rect.bottom <= page_height
        ):
            raise exceptions.DecoderException(
                f"TITLERECT {rect.to_wire()} outside page bounds {page_width}x{page_height}"
            )

        decoder = self.find_decoder(
            title,
            highres_grayscale=self.note.supports_highres_grayscale(),
            default_protocol=schema.LayerProtocol.RATTA_RLE,
        )
        try:
            img = self._create_image_from_decoder(
                decoder,
                title.content,
                palette=self.palette,
                width=rect.width,
                height=rect.height,
            )
        except exceptions.DecoderException as crop_err:
            # Legacy firmware (e.g. SN_FILE_VER_20220011) stores a full-page
            # RLE bitmap in TITLEBITMAP; decode at page size and crop to rect.
            try:
                full_img = self._create_image_from_decoder(
                    decoder,
                    title.content,
                    palette=self.palette,
                    horizontal=horizontal,
                )
            except exceptions.DecoderException:
                raise crop_err from None
            img = full_img.crop(rect.bbox)

        return self._whiten_transparent(img)

    def _convert_nonlayered_page(
        self, page, palette=None, visibility_overlay=None, highres_grayscale=False
    ):
        binary = page.content
        if binary is None:
            return Image.new(
                "L",
                (self.note.width, self.note.height),
                color=color.TRANSPARENT,
            )
        decoder = self.find_decoder(page)
        return self._create_image_from_decoder(decoder, binary, palette=palette)

    def _convert_layered_page(
        self, page, palette=None, visibility_overlay=None, highres_grayscale=False
    ):
        default_palette = color.DEFAULT_COLORPALETTE
        page = utils.WorkaroundPageWrapper.from_page(page)
        visibility = self._get_layer_visibility(page)
        layers_by_name = {
            str(layer.name): layer for layer in page.layers if layer.name is not None
        }
        horizontal = page.is_horizontal()
        page_width, page_height = (self.note.width, self.note.height)
        if horizontal:
            page_height, page_width = (page_width, page_height)
        flatten_img = Image.new(
            "RGB", (page_width, page_height), color=color.RGB_TRANSPARENT
        )
        page_style = page.style
        for layer_name in reversed(page.layer_order):
            if not self._is_layer_visible(layer_name, visibility, visibility_overlay):
                continue
            layer = layers_by_name.get(layer_name)
            if layer is None:
                continue
            binary = layer.content
            if binary is None:
                continue
            binary_size = len(binary)
            all_blank = (
                layer_name == "BGLAYER"
                and page_style is not None
                and page_style == "style_white"
                and binary_size == self.SPECIAL_WHITE_STYLE_BLOCK_SIZE
            )
            if all_blank:
                continue
            decoder = self.find_decoder(
                layer,
                highres_grayscale,
                default_protocol=schema.LayerProtocol.RATTA_RLE,
            )
            plt = default_palette if layer_name == "BGLAYER" else palette
            img_layer = self._create_image_from_decoder(
                decoder,
                binary,
                palette=plt,
                blank_hint=all_blank,
                horizontal=horizontal,
            )
            if layer_name == "BGLAYER":
                # convert transparent to white for custom template
                img_layer = self._whiten_transparent(img_layer)
            if img_layer.mode == "RGBA":
                mask = img_layer.getchannel("A")
            else:
                mask_src = (
                    img_layer if img_layer.mode == "L" else img_layer.convert("L")
                )
                mask = mask_src.point(_NON_TRANSPARENT_LUT, mode="1")
            flatten_img.paste(img_layer, None, mask)
        return flatten_img

    @staticmethod
    def _is_layer_visible(layer_name, visibility, visibility_overlay=None):
        is_visible = bool(visibility.get(layer_name))
        if visibility_overlay is None:
            return is_visible
        overlay = visibility_overlay.get(layer_name)
        if overlay == VisibilityOverlay.INVISIBLE:
            return False
        if overlay == VisibilityOverlay.VISIBLE:
            return True
        return is_visible

    def _whiten_transparent(self, img):
        if img.mode in ("L", "RGB"):
            return img
        img = img.convert("RGBA")
        newImg = Image.new("RGB", img.size, color.RGB_WHITE)
        newImg.paste(img, mask=img)
        return newImg

    def _make_transparent(self, img):
        transparent_img = Image.new("RGBA", img.size, (255, 255, 255, 0))
        mask_src = img if img.mode == "L" else img.convert("L")
        mask = mask_src.point(_TRANSPARENT_LUT, mode="1")
        img = img.convert("RGBA")
        return Image.composite(transparent_img, img, mask)

    def _create_image_from_decoder(
        self,
        decoder,
        binary,
        palette=None,
        blank_hint=False,
        horizontal=False,
        width=None,
        height=None,
    ):
        page_width = self.note.width if width is None else width
        page_height = self.note.height if height is None else height
        bitmap, size, bpp = decoder.decode(
            binary,
            page_width,
            page_height,
            palette=palette,
            all_blank=blank_hint,
            horizontal=horizontal,
        )
        if bpp == 32:
            img = Image.frombytes("RGBA", size, bitmap)
        elif bpp == 24:
            img = Image.frombytes("RGB", size, bitmap)
        elif bpp == 16 and isinstance(decoder, Decoder.PngDecoder):
            img = Image.frombytes("LA", size, bitmap)
        elif bpp == 16:
            img = Image.frombytes("I;16", size, bitmap)
        elif bpp == 8:
            img = Image.frombytes("L", size, bitmap)
        else:
            raise exceptions.DecoderException(f"Unsupported bit depth: {bpp}")
        return img

    def _get_layer_visibility(self, page: fileformat.Page) -> dict[str, bool]:
        return page.layer_visibility

    @staticmethod
    def _resolve_protocol(
        target: fileformat.Page | fileformat.Layer | fileformat.Title,
        default_protocol: str | None = None,
    ) -> str | None:
        if isinstance(target, fileformat.Layer):
            if target.protocol is None and (
                target.content is None
                or not target.content.startswith(Decoder.PNG_SIGNATURE)
            ):
                return default_protocol
            return target.bitmap_protocol
        if target.content is not None and target.content.startswith(
            Decoder.PNG_SIGNATURE
        ):
            return schema.LayerProtocol.PNG
        return target.protocol if target.protocol is not None else default_protocol

    def find_decoder(
        self,
        page,
        highres_grayscale=False,
        default_protocol: str | None = None,
    ):
        """Return the bitmap decoder for `page` (or `Layer` / `Title`), falling back to `default_protocol` when omitted."""
        protocol = self._resolve_protocol(page, default_protocol)
        if protocol == schema.LayerProtocol.SN_ASA_COMPRESS:
            return Decoder.FlateDecoder()
        if protocol == schema.LayerProtocol.RATTA_RLE:
            if highres_grayscale:
                return Decoder.RattaRleX2Decoder()
            return Decoder.RattaRleDecoder()
        if protocol == schema.LayerProtocol.PNG:
            return Decoder.PngDecoder()
        raise exceptions.UnknownDecodeProtocol(f"unknown decode protocol: {protocol}")


class SvgConverter:
    def __init__(self, notebook, palette=None):
        self.note = notebook
        self.palette = palette if palette is not None else color.DEFAULT_COLORPALETTE
        self.image_converter = ImageConverter(
            notebook, palette=color.DEFAULT_COLORPALETTE
        )  # use default palette

    def convert(self, page_number, visibility_overlay=None):
        """Returns SVG string of the given page.

        Parameters
        ----------
        page_number : int
            page number to convert

        Returns
        -------
        string
            an SVG string
        """
        page = self.note.page(page_number)
        horizontal = page.is_horizontal()
        page_width, page_height = (self.note.width, self.note.height)
        if horizontal:
            page_height, page_width = (page_width, page_height)
        dwg = svgwrite.Drawing(
            "dummy.svg", profile="full", size=(page_width, page_height)
        )

        bg_is_invisible = (
            visibility_overlay is not None
            and visibility_overlay.get("BGLAYER") == VisibilityOverlay.INVISIBLE
        )
        if not bg_is_invisible:
            vo_only_bg = build_visibility_overlay(
                background=VisibilityOverlay.VISIBLE,
                main=VisibilityOverlay.INVISIBLE,
                layer1=VisibilityOverlay.INVISIBLE,
                layer2=VisibilityOverlay.INVISIBLE,
                layer3=VisibilityOverlay.INVISIBLE,
            )
            bg_img = self.image_converter.convert(
                page_number, visibility_overlay=vo_only_bg
            )
            buffer = BytesIO()
            bg_img.save(buffer, format="png")
            bg_b64str = base64.b64encode(buffer.getvalue()).decode("ascii")
            dwg.add(
                dwg.image(
                    "data:image/png;base64," + bg_b64str,
                    insert=(0, 0),
                    size=(page_width, page_height),
                )
            )

        vo_except_bg = build_visibility_overlay(background=VisibilityOverlay.INVISIBLE)
        img = self.image_converter.convert(page_number, visibility_overlay=vo_except_bg)

        def generate_color_mask(img, c):
            mask = img.copy().convert("L")
            return mask.point(lambda x: 0 if x == c else 1, mode="1")

        default_palette = color.DEFAULT_COLORPALETTE
        default_color_list = [
            default_palette.black,
            default_palette.darkgray,
            default_palette.gray,
            default_palette.white,
        ]
        user_color_list = [
            self.palette.black,
            self.palette.darkgray,
            self.palette.gray,
            self.palette.white,
        ]
        for i, c in enumerate(default_color_list):
            user_color = user_color_list[i]
            mask = generate_color_mask(img, c)
            # create a bitmap from the array
            bmp = potrace.Bitmap(mask)
            # trace the bitmap to a path
            path = bmp.trace()
            # iterate over path curves
            if len(path) > 0:
                svgpath = dwg.path(
                    fill=color.web_string(user_color, mode=self.palette.mode)
                )
                for curve in path:
                    start = curve.start_point
                    svgpath.push("M", start.x, start.y)
                    for segment in curve:
                        end = segment.end_point
                        if segment.is_corner:
                            c = segment.c
                            svgpath.push("L", c.x, c.y)
                            svgpath.push("L", end.x, end.y)
                        else:
                            c1 = segment.c1
                            c2 = segment.c2
                            svgpath.push("C", c1.x, c1.y, c2.x, c2.y, end.x, end.y)
                    svgpath.push("Z")
                dwg.add(svgpath)
        return dwg.tostring()


@dataclass(frozen=True)
class PdfOutlineEntry:
    """A single PDF Table of Contents outline bookmark entry."""

    title: str
    """Display text shown in the PDF reader's outline/bookmarks panel."""

    page_index: int
    """0-based notebook page index the bookmark navigates to."""

    level: int = 1
    """1-based heading nesting depth (clamped to valid PDF outline nesting)."""


_PDF_TEXT_FONT = "Helvetica"
# ReportLab's built-in Unicode CID font requires no bundled TTF files and
# encodes CJK + ASCII as UCS-2 so non-Latin OCR transcripts stay searchable
# instead of degrading to placeholder glyphs under Helvetica/WinAnsi.
_PDF_TEXT_CJK_FONT = "STSong-Light"
_CJK_CHAR_RE = re.compile(
    r"[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]"
)
_PDF_TEXT_DEFAULT_SIZE = 10.0
_PDF_TEXT_MIN_SIZE = 1.0
_PDF_TEXT_LEADING_RATIO = 1.2
_PDF_TEXT_MARGIN = 18.0
# PDF text rendering mode 3 ("neither fill nor stroke" in ISO 32000-1 §9.3.6):
# draws the OCR transcript as an invisible overlay so PDF readers can search
# and index the page without altering the rendered handwriting image.
_PDF_TEXT_RENDER_INVISIBLE = 3


class PdfConverter:
    class ImgPageRenderer:
        def __init__(self, img: Image.Image, pagesize):
            self.img = img
            self.pagesize = pagesize

        def get_scale(self):
            (w, h) = self.pagesize
            return (w / self.img.width, h / self.img.height)

        def draw(self, cvs):
            (w, h) = self.pagesize
            cvs.drawInlineImage(self.img, 0, 0, width=w, height=h)

    def __init__(self, notebook: Notebook, palette: ColorPalette | None = None) -> None:
        self.note = notebook
        self.palette = palette
        self.pagesize = A4

    def convert(
        self,
        page_indices: int | list[int],
        enable_link: bool = False,
        enable_keyword: bool = False,
        *,
        page_texts: Mapping[int, str] | None = None,
        toc_entries: Sequence[PdfOutlineEntry] | None = None,
    ) -> bytes:
        """Returns PDF data of the given page(s).

        Parameters
        ----------
        page_indices : int | list[int]
            page number to convert, -1 for all, or a list of page numbers
        enable_link : bool
            enable page links and web links
        enable_keyword : bool
            enable page link where keyword has been identified
        page_texts : Mapping[int, str] | None
            optional 0-based page index to plain text mapping embedded as an
            invisible searchable text layer on each matching page
        toc_entries : Sequence[PdfOutlineEntry] | None
            optional ordered Table of Contents outline entries; entries whose
            page is not included or whose title is blank are skipped

        Returns
        -------
        data : bytes
            bytes of PDF data
        """
        converter = ImageConverter(self.note, self.palette)
        renderer_class = PdfConverter.ImgPageRenderer
        imglist = self._create_image_list(converter, page_indices)
        pdf_data = BytesIO()
        self._create_pdf(
            pdf_data,
            imglist,
            renderer_class,
            enable_link,
            enable_keyword,
            page_texts=page_texts,
            toc_entries=toc_entries,
        )
        return pdf_data.getvalue()

    def _create_image_list(
        self, converter: ImageConverter, page_indices: int | list[int]
    ) -> list[tuple[int, Image.Image]]:
        imglist = []
        if isinstance(page_indices, int):
            if page_indices < 0:
                indices = list(range(self.note.total_pages))
            else:
                indices = [page_indices]
        else:
            indices = page_indices

        for i in indices:
            img = converter.convert(i)
            imglist.append((i, img))
        return imglist

    def _create_pdf(
        self,
        buf: BytesIO,
        imglist: list[tuple[int, Image.Image]],
        renderer_class: type[ImgPageRenderer],
        enable_link: bool,
        enable_keyword: bool,
        *,
        page_texts: Mapping[int, str] | None = None,
        toc_entries: Sequence[PdfOutlineEntry] | None = None,
    ) -> None:
        c = canvas.Canvas(buf, pagesize=self.pagesize)
        # Group non-empty TOC entries by page so each entry gets its own unique
        # bookmark key on that page (ReportLab's outline map keys entries by
        # destination name, so reusing one key per page overwrites earlier titles).
        toc_keys_by_page: dict[int, list[str]] = {}
        if toc_entries:
            for entry_idx, entry in enumerate(toc_entries):
                if entry.title.strip():
                    toc_keys_by_page.setdefault(entry.page_index, []).append(
                        f"toc_entry_{entry_idx}"
                    )
        bookmarked_keys: set[str] = set()

        for page_idx, img in imglist:
            page = self.note.page(page_idx)
            pageid = page.page_id
            horizontal = page.is_horizontal()
            pagesize = (
                landscape(self.pagesize) if horizontal else portrait(self.pagesize)
            )
            c.setPageSize(pagesize)
            renderer = renderer_class(img, pagesize)
            renderer.draw(c)
            if page_texts is not None:
                page_text = page_texts.get(page_idx)
                if page_text:
                    self._draw_invisible_text(c, page_text, pagesize)
            for toc_key in toc_keys_by_page.get(page_idx, ()):
                if toc_key not in bookmarked_keys:
                    c.bookmarkPage(toc_key)
                    bookmarked_keys.add(toc_key)
            if enable_keyword:
                for keyword in page.keywords:
                    try:
                        c.bookmarkPage(pageid)
                        scaled_rect = self._calc_link_rect(
                            keyword.rect, renderer.get_scale()
                        )
                        c.textAnnotation(keyword.keyword, scaled_rect)
                    except Exception:
                        continue
            if enable_link:
                pageid = page.page_id
                if pageid is not None:
                    c.bookmarkPage(pageid)
                    self._add_links(c, page, renderer.get_scale())
            c.showPage()

        if toc_entries:
            self._add_outline_entries(c, toc_entries, bookmarked_keys)
        c.save()

    @staticmethod
    def _select_text_font(text: str) -> str:
        """Select Helvetica for Latin text or a built-in Unicode CID font for CJK."""
        if not _CJK_CHAR_RE.search(text):
            return _PDF_TEXT_FONT
        if _PDF_TEXT_CJK_FONT not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont(_PDF_TEXT_CJK_FONT))
        return _PDF_TEXT_CJK_FONT

    @staticmethod
    def _draw_invisible_text(
        cvs: canvas.Canvas, text: str, pagesize: tuple[float, float]
    ) -> None:
        """Embed an invisible, searchable text layer fitted inside `pagesize`."""
        width, height = pagesize
        usable_width = max(width - 2 * _PDF_TEXT_MARGIN, 1.0)
        usable_height = max(height - 2 * _PDF_TEXT_MARGIN, 1.0)

        font_name = PdfConverter._select_text_font(text)
        font_size = _PDF_TEXT_DEFAULT_SIZE
        wrapped_lines = PdfConverter._wrap_text_lines(
            text, font_name, font_size, usable_width
        )
        if not wrapped_lines:
            return

        leading = font_size * _PDF_TEXT_LEADING_RATIO
        if len(wrapped_lines) * leading > usable_height:
            # Shrink proportionally so dense transcripts fit inside the page box
            # without clipping off the bottom edge in PDF text indexers.
            scale = usable_height / (len(wrapped_lines) * leading)
            font_size = max(_PDF_TEXT_MIN_SIZE, font_size * scale)
            leading = font_size * _PDF_TEXT_LEADING_RATIO
            wrapped_lines = PdfConverter._wrap_text_lines(
                text, font_name, font_size, usable_width
            )

        text_obj = cvs.beginText(
            _PDF_TEXT_MARGIN, height - _PDF_TEXT_MARGIN - font_size
        )
        text_obj.setFont(font_name, font_size, leading=leading)
        text_obj.setTextRenderMode(_PDF_TEXT_RENDER_INVISIBLE)
        text_obj.textLines(wrapped_lines)
        cvs.drawText(text_obj)

    @staticmethod
    def _wrap_text_lines(
        text: str, font_name: str, font_size: float, max_width: float
    ) -> list[str]:
        """Split `text` into wrapped lines that fit within `max_width`."""
        lines: list[str] = []
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            lines.extend(simpleSplit(stripped, font_name, font_size, max_width))
        return lines

    @staticmethod
    def _add_outline_entries(
        cvs: canvas.Canvas,
        toc_entries: Sequence[PdfOutlineEntry],
        bookmarked_keys: set[str],
    ) -> None:
        """Emit PDF outline entries for included pages, normalizing level jumps."""
        # Maintain a monotonic stack of original 0-based heading levels so
        # non-contiguous Supernote styles satisfy ReportLab's `level <= prev + 1`
        # invariant while preserving sibling and parent-child relationships.
        level_stack: list[int] = []
        for entry_idx, entry in enumerate(toc_entries):
            toc_key = f"toc_entry_{entry_idx}"
            if toc_key not in bookmarked_keys:
                continue
            target_level = max(0, entry.level - 1)
            while level_stack and level_stack[-1] >= target_level:
                level_stack.pop()
            cvs.addOutlineEntry(entry.title.strip(), toc_key, level=len(level_stack))
            level_stack.append(target_level)

    def _add_links(
        self, cvs: canvas.Canvas, page: fileformat.Page, scale: tuple[float, float]
    ) -> None:
        for link in page.links:
            if link.direction == fileformat.Link.DIRECTION_IN:
                # ignore income link
                continue
            link_type = link.link_type
            is_internal_link = link.file_id == self.note.file_id
            if link_type == fileformat.Link.TYPE_PAGE_LINK and is_internal_link:
                tag = link.page_id
                if tag is not None:
                    scaled_rect = self._calc_link_rect(link.rect, scale)
                    cvs.linkAbsolute("Link", tag, scaled_rect)
            elif link_type == fileformat.Link.TYPE_WEB_LINK:
                url = link.target
                if url is not None:
                    scaled_rect = self._calc_link_rect(link.rect, scale)
                    cvs.linkURL(url, scaled_rect)

    def _calc_link_rect(self, rect, scale):
        (left, top, right, bottom) = rect
        (scale_x, scale_y) = scale
        (w, h) = self.pagesize
        return (
            left * scale_x,
            h - top * scale_y,
            right * scale_x,
            h - bottom * scale_y,
        )


class TextConverter:
    def __init__(self, notebook: fileformat.Notebook, palette=None) -> None:
        self.note = notebook
        self.palette = palette

    def convert(self, page_number: int) -> str | None:
        """Returns text of the given page if available.

        Text elements are sorted top-to-bottom and joined intelligently
        with newlines and spaces based on vertical spacing.

        Parameters
        ----------
        page_number : int
            page number to convert

        Returns
        -------
        string
            a recognized text if available, otherwise None
        """
        if not self.note.is_realtime_recognition():
            return None
        page = self.note.page(page_number)
        if page.recogn_status != fileformat.Page.RECOGNSTATUS_DONE:
            return None
        binary = page.recogn_text
        decoder = Decoder.TextDecoder()
        elements = decoder.decode(binary)
        if elements is None:
            return None

        # Sort elements by y-position (top to bottom)
        elements.sort(key=lambda e: e.y)

        # Join elements intelligently based on vertical spacing
        result = []
        for i, elem in enumerate(elements):
            if i > 0:
                prev_elem = elements[i - 1]
                # Check vertical gap between elements
                y_gap = elem.y - prev_elem.y

                # Use newline if vertical gap > 3 units
                if y_gap > 3:
                    result.append("\n")
                else:
                    result.append(" ")
            result.append(elem.label)

        text = "".join(result)

        # Fix spacing around punctuation (preserve newlines)
        fixed_lines = []
        for line in text.split("\n"):
            # Remove space before closing punctuation
            line = re.sub(r" +([,.)!?;:\]])", r"\1", line)
            # Remove space after opening punctuation
            line = re.sub(r"([\[(]) +", r"\1", line)

            # Fix spaces between quotes and words
            line = re.sub(r'"\s+(\w)', r'"\1', line)
            line = re.sub(r"(\w)\s+\"", r'\1"', line)
            line = re.sub(r"(\w)\"(\w)", r'\1 "\2', line)

            # Fix double spaces
            line = re.sub(r" {2,}", " ", line)
            line = line.strip()
            if line:  # Only add non-empty lines
                fixed_lines.append(line)

        text = "\n".join(fixed_lines)

        return text if text else None


# Alias for backward compatibility
PngConverter = ImageConverter
