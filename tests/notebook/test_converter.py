import base64
import io
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, ImageChops
from syrupy.extensions.image import PNGImageSnapshotExtension

from supernote.notebook import (
    ColorPalette,
    ImageConverter,
    PdfConverter,
    PngConverter,
    SvgConverter,
    TextConverter,
    VisibilityOverlay,
    color,
    exceptions,
    fileformat,
    load_notebook,
)
from supernote.notebook import (
    decoder as decoder_mod,
)
from supernote.notebook.color import (
    MODE_RGB,
    RGB_BLACK,
    RGB_DARK_GRAY,
    RGB_GRAY,
    RGB_WHITE,
)
from supernote.notebook.converter import build_visibility_overlay
from supernote.notebook.decoder import TextElement
from supernote.notebook.exceptions import DecoderException

from .conftest import (
    HORIZONTAL_NOTE_PATH,
    ONE_TO_TEN_NOTE_PATH,
    STROLLER_NOTE_PATH,
    TEST_DATA_DIR,
    FakeDecoder,
)

NOTE_PATHS = sorted(TEST_DATA_DIR.glob("**/*.note"))


@lru_cache(maxsize=32)
def get_cached_notebook(note_path_str: str) -> fileformat.Notebook:
    return load_notebook(note_path_str)


class VisualPngSnapshotExtension(PNGImageSnapshotExtension):
    """Custom syrupy extension that stores snapshots as raw PNG files

    but compares them using pixel data difference (ImageChops) to be robust
    across different platforms and zlib/Pillow library versions.
    """

    def matches(self, *, serialized_data, snapshot_data) -> bool:
        if not serialized_data or not snapshot_data:
            return False
        try:
            img_new = Image.open(io.BytesIO(serialized_data))
            img_golden = Image.open(io.BytesIO(snapshot_data))

            if img_new.size != img_golden.size or img_new.mode != img_golden.mode:
                return False

            diff = ImageChops.difference(img_new, img_golden).getbbox()
            return diff is None
        except Exception:
            return False


def _serialize_notebook_metadata(notebook: fileformat.Notebook) -> dict:
    """Extract structural metadata that is serializable and useful for regression checks."""
    return {
        "type": notebook.get_type(),
        "signature": notebook.get_signature(),
        "width": notebook.get_width(),
        "height": notebook.get_height(),
        "total_pages": notebook.get_total_pages(),
        "keywords": [kw.metadata for kw in notebook.get_keywords()],
        "titles": [t.metadata for t in notebook.get_titles()],
        "links": [link.metadata for link in notebook.get_links()],
    }


@pytest.mark.parametrize("note_path", NOTE_PATHS, ids=lambda p: p.name)
def test_notebook_metadata_snapshot(note_path: Path, snapshot) -> None:
    notebook = get_cached_notebook(str(note_path))
    metadata_snapshot = _serialize_notebook_metadata(notebook)
    assert metadata_snapshot == snapshot


@pytest.mark.parametrize("note_path", NOTE_PATHS, ids=lambda p: p.name)
def test_notebook_png_snapshots(note_path: Path, snapshot) -> None:
    notebook = get_cached_notebook(str(note_path))
    converter = PngConverter(notebook)
    total_pages = notebook.get_total_pages()

    for p in range(total_pages):
        img = converter.convert(p)

        buf = io.BytesIO()
        img.save(buf, format="PNG", compress_level=1)
        png_bytes = buf.getvalue()

        assert png_bytes == snapshot(
            name=f"page_{p}", extension_class=VisualPngSnapshotExtension
        )


@pytest.mark.parametrize("note_path", NOTE_PATHS, ids=lambda p: p.name)
def test_notebook_text_snapshots(note_path: Path, snapshot) -> None:
    notebook = get_cached_notebook(str(note_path))
    texts = {}
    if notebook.is_realtime_recognition():
        converter = TextConverter(notebook)
        total_pages = notebook.get_total_pages()

        for p in range(total_pages):
            texts[f"page_{p}"] = converter.convert(p)

    assert texts == snapshot


# --- ImageConverter Unit Tests ---


@pytest.mark.parametrize("bpp", [0, 7, 12])
def test_image_converter_rejects_unsupported_bit_depth(
    bpp: int, make_notebook: Callable[..., fileformat.Notebook]
) -> None:
    notebook = make_notebook(width=1, height=1)
    converter = ImageConverter(notebook)
    with pytest.raises(DecoderException, match=f"{bpp}"):
        converter._create_image_from_decoder(
            FakeDecoder(b"\x00", size=(1, 1), bpp=bpp), b"unused"
        )


@pytest.mark.parametrize(
    ("bitmap", "bpp", "expected_mode", "expected_pixel"),
    [
        (b"\x80", 8, "L", 128),
        (b"\x10\x20", 16, "I;16", 0x2010),
        (b"\x10\x20\x30", 24, "RGB", (0x10, 0x20, 0x30)),
        (b"\x10\x20\x30\xff", 32, "RGBA", (0x10, 0x20, 0x30, 0xFF)),
    ],
)
def test_image_converter_supported_bit_depths(
    bitmap: bytes,
    bpp: int,
    expected_mode: str,
    expected_pixel: int | tuple[int, ...],
    make_notebook: Callable[..., fileformat.Notebook],
) -> None:
    notebook = make_notebook(width=1, height=1)
    converter = ImageConverter(notebook)
    img = converter._create_image_from_decoder(
        FakeDecoder(bitmap, size=(1, 1), bpp=bpp), b"unused"
    )
    assert img.mode == expected_mode
    assert img.getpixel((0, 0)) == expected_pixel


def test_image_converter_16bpp_png_decoder_uses_la_mode(
    make_notebook: Callable[..., fileformat.Notebook],
) -> None:
    notebook = make_notebook(width=1, height=1)
    converter = ImageConverter(notebook)
    png_decoder = decoder_mod.PngDecoder()
    with patch.object(png_decoder, "decode", return_value=(b"\x40\xff", (1, 1), 16)):
        img = converter._create_image_from_decoder(png_decoder, b"unused")
    assert img.mode == "LA"
    assert img.getpixel((0, 0)) == (0x40, 0xFF)


def test_image_converter_nonlayered_page_and_find_decoder(
    make_notebook: Callable[..., fileformat.Notebook],
) -> None:
    notebook = make_notebook(
        width=2,
        height=2,
        pages=[
            {"PAGEID": "P0", "PROTOCOL": "RATTA_RLE"},
            {"PAGEID": "P1", "PROTOCOL": "SN_ASA_COMPRESS"},
            {"PAGEID": "P2", "PROTOCOL": "UNKNOWN_PROTO"},
        ],
    )
    converter = ImageConverter(notebook)

    # Empty content returns a blank transparent grayscale image
    blank_img = converter.convert(0)
    assert blank_img.mode == "L"
    assert blank_img.size == (2, 2)
    assert blank_img.getpixel((0, 0)) == color.TRANSPARENT

    # Non-layered page with RATTA_RLE content decodes via RattaRleDecoder
    notebook.get_page(0).set_content(
        bytes([decoder_mod.RattaRleDecoder.COLORCODE_BLACK, 3])
    )
    decoded_img = converter.convert(0)
    assert decoded_img.mode == "L"
    assert decoded_img.size == (2, 2)
    assert decoded_img.getpixel((0, 0)) == color.BLACK

    # find_decoder returns FlateDecoder for SN_ASA_COMPRESS and raises on unknown protocol
    assert isinstance(
        converter.find_decoder(notebook.get_page(1)), decoder_mod.FlateDecoder
    )
    with pytest.raises(exceptions.UnknownDecodeProtocol, match="UNKNOWN_PROTO"):
        converter.find_decoder(notebook.get_page(2))


def test_image_converter_special_white_style_and_visibility_overlay(
    make_notebook: Callable[..., fileformat.Notebook],
) -> None:
    layer_info = (
        '[{"layerId": 0, "isBackgroundLayer": true, "isVisible": true}, '
        '{"layerId": 0, "isBackgroundLayer": false, "isVisible": false}, '
        '{"layerId": 1, "isBackgroundLayer": false, "isVisible": true}]'
    )
    notebook = make_notebook(
        width=2,
        height=2,
        pages=[
            {
                "PAGEID": "P1",
                "PAGESTYLE": "style_white",
                "LAYERINFO": layer_info.replace(":", "#"),
                "LAYERSEQ": "MAINLAYER,LAYER1,BGLAYER,MISSING",
                fileformat.KEY_LAYERS: [
                    {"LAYERNAME": "MAINLAYER", "LAYERPROTOCOL": "RATTA_RLE"},
                    {"LAYERNAME": "LAYER1", "LAYERPROTOCOL": "RATTA_RLE"},
                    {"LAYERNAME": "LAYER2", "LAYERPROTOCOL": "RATTA_RLE"},
                    {"LAYERNAME": "LAYER3", "LAYERPROTOCOL": "RATTA_RLE"},
                    {"LAYERNAME": "BGLAYER", "LAYERPROTOCOL": "RATTA_RLE"},
                ],
            }
        ],
    )
    page = notebook.get_page(0)
    page.get_layer(0).set_content(
        bytes([decoder_mod.RattaRleDecoder.COLORCODE_BLACK, 3])
    )
    # LAYER1 is visible in LAYERINFO but has None content -> skipped cleanly
    page.get_layer(1).set_content(None)
    # BGLAYER with style_white and SPECIAL_WHITE_STYLE_BLOCK_SIZE (0x140E) is skipped as all_blank
    page.get_layer(4).set_content(
        b"\x00" * ImageConverter.SPECIAL_WHITE_STYLE_BLOCK_SIZE
    )

    converter = ImageConverter(notebook)
    overlay = build_visibility_overlay(
        background=VisibilityOverlay.DEFAULT,
        main=VisibilityOverlay.VISIBLE,
    )
    img = converter.convert(0, visibility_overlay=overlay)
    assert img.size == (2, 2)
    assert img.getpixel((0, 0)) == (0, 0, 0)


@pytest.mark.parametrize(
    ("layer_info", "expected_visibility"),
    [
        (
            '[{"layerId": 0, "isBackgroundLayer": false, "isVisible": true}]',
            {"MAINLAYER": True},
        ),
        (
            "W3sibGF5ZXJJZCI6IDAsICJpc0JhY2tncm91bmRMYXllciI6IGZhbHNlLCAiaXNWaXNpYmxlIjogdHJ1ZX1d",
            {"MAINLAYER": True},
        ),
        (
            '[{"layerId": 0, "isBackgroundLayer": true, "isVisible": false}, '
            '{"layerId": 2, "isBackgroundLayer": false, "isVisible": true}]',
            {"BGLAYER": False, "LAYER2": True, "MAINLAYER": True},
        ),
    ],
)
def test_get_layer_visibility(
    layer_info: str,
    expected_visibility: dict[str, bool],
    make_notebook: Callable[..., fileformat.Notebook],
) -> None:
    converter = ImageConverter(make_notebook())
    page = fileformat.Page({"LAYERINFO": layer_info.replace(":", "#")})
    assert converter._get_layer_visibility(page) == expected_visibility


def test_get_layer_visibility_mark_fallback(
    make_notebook: Callable[..., fileformat.Notebook],
) -> None:
    converter = ImageConverter(make_notebook())
    page = fileformat.Page(
        {
            "LAYERINFO": "none",
            fileformat.KEY_LAYERS: [
                {"LAYERNAME": "MAINLAYER", "LAYERTYPE": "MARK"},
                {"LAYERNAME": "LAYER1", "LAYERTYPE": "NOTE"},
                {"LAYERNAME": "LAYER2", "LAYERTYPE": "NOTE"},
                {"LAYERNAME": "LAYER3", "LAYERTYPE": "NOTE"},
                {"LAYERNAME": "BGLAYER", "LAYERTYPE": "BACKGROUND"},
            ],
        }
    )
    assert converter._get_layer_visibility(page) == {
        "MAINLAYER": True,
        "LAYER1": False,
        "LAYER2": False,
        "LAYER3": False,
        "BGLAYER": False,
    }


@pytest.mark.parametrize(
    "layer_info",
    [
        "!!!not-base64!!!",  # malformed base64
        base64.b64encode(b"\xff\xfe\x00bad").decode(),  # base64 of non-UTF-8 bytes
        base64.b64encode(b"just a string").decode(),  # base64 of non-JSON text
        "not json at all {{{",  # neither JSON nor decodable base64 JSON
        "123",  # valid JSON primitive, not a list
        "[1, 2]",  # valid JSON list of non-dict items
    ],
)
def test_get_layer_visibility_malformed_payload(
    layer_info: str, make_notebook: Callable[..., fileformat.Notebook]
) -> None:
    converter = ImageConverter(make_notebook())
    page = fileformat.Page({"LAYERINFO": layer_info})

    with pytest.raises(exceptions.ParserException, match="invalid layer info payload"):
        converter._get_layer_visibility(page)


# --- TextConverter Unit Tests ---


def test_text_converter_formatting(
    make_notebook: Callable[..., fileformat.Notebook],
) -> None:
    notebook = make_notebook(
        header={"FILE_TYPE": "NOTE", "FILE_RECOGN_TYPE": "1"},
        pages=[
            {"PAGEID": "P1", "RECOGNSTATUS": str(fileformat.Page.RECOGNSTATUS_DONE)}
        ],
    )
    notebook.get_page(0).set_recogn_text(b"dummy_binary")

    elements = [
        TextElement(label="Hello", y=10),
        TextElement(label="world", y=12),  # gap <= 3 -> space
        TextElement(label="!", y=12),  # punctuation cleanup -> "world!"
        TextElement(label="This is a new line", y=20),  # gap > 3 -> newline
        TextElement(
            label=" ( with parens ) ", y=20
        ),  # punctuation cleanup -> "(with parens)"
    ]

    with patch("supernote.notebook.decoder.TextDecoder.decode", return_value=elements):
        converter = TextConverter(notebook)
        result = converter.convert(0)

    assert result == "Hello world!\nThis is a new line (with parens)"


def test_text_converter_edge_cases(sample_notebook: fileformat.Notebook) -> None:
    converter = TextConverter(sample_notebook)

    # non-realtime notebook returns None
    assert converter.convert(0) is None

    # status != RECOGNSTATUS_DONE
    with patch.object(sample_notebook, "is_realtime_recognition", return_value=True):
        with patch.object(
            sample_notebook.get_page(0), "get_recogn_status", return_value=0
        ):
            assert converter.convert(0) is None

    # decode returns None
    with patch.object(sample_notebook, "is_realtime_recognition", return_value=True):
        with patch.object(
            sample_notebook.get_page(0), "get_recogn_status", return_value=1
        ):
            with patch(
                "supernote.notebook.decoder.TextDecoder.decode", return_value=None
            ):
                assert converter.convert(0) is None


# --- SVG Converter Tests ---


def test_svg_converter_export(sample_notebook: fileformat.Notebook) -> None:
    converter = SvgConverter(sample_notebook)
    svg_str = converter.convert(0)
    assert isinstance(svg_str, str)
    assert "<svg" in svg_str
    assert "</svg>" in svg_str


def test_svg_converter_horizontal_and_visibility() -> None:
    notebook = load_notebook(str(HORIZONTAL_NOTE_PATH))
    custom_palette = ColorPalette(
        MODE_RGB,
        (RGB_BLACK, RGB_DARK_GRAY, RGB_GRAY, RGB_WHITE),
    )
    converter = SvgConverter(notebook, palette=custom_palette)

    vo_invisible_bg = build_visibility_overlay(background=VisibilityOverlay.INVISIBLE)
    svg_str = converter.convert(0, visibility_overlay=vo_invisible_bg)
    assert isinstance(svg_str, str)
    assert "<svg" in svg_str


# --- PDF Converter Tests ---


def test_pdf_converter_basic_export(sample_notebook: fileformat.Notebook) -> None:
    pdf_converter = PdfConverter(sample_notebook)

    pdf_bytes = pdf_converter.convert(0)
    assert pdf_bytes.startswith(b"%PDF-")

    all_pdf_bytes = pdf_converter.convert(-1)
    assert all_pdf_bytes.startswith(b"%PDF-")

    list_pdf_bytes = pdf_converter.convert([0])
    assert list_pdf_bytes.startswith(b"%PDF-")


def test_pdf_converter_keywords_and_landscape() -> None:
    notebook = load_notebook(str(STROLLER_NOTE_PATH))
    pdf_converter = PdfConverter(notebook)

    pdf_bytes = pdf_converter.convert(0, enable_keyword=True)
    assert pdf_bytes.startswith(b"%PDF-")

    horiz_nb = load_notebook(str(HORIZONTAL_NOTE_PATH))
    horiz_pdf_converter = PdfConverter(horiz_nb)
    horiz_pdf_bytes = horiz_pdf_converter.convert(0)
    assert horiz_pdf_bytes.startswith(b"%PDF-")


def test_pdf_converter_links(sample_notebook: fileformat.Notebook) -> None:
    page0 = sample_notebook.get_page(0)
    page0.metadata["PAGEID"] = "P0001"

    web_url_b64 = base64.b64encode(b"https://example.com").decode()
    l_internal = fileformat.Link(
        {
            "LINKTYPE": "0",
            "LINKINOUT": "0",
            "LINKRECT": "10,20,30,40",
            "LINKTIMESTAMP": "12345",
            "LINKFILE": "test.note",
            "LINKFILEID": str(sample_notebook.get_fileid()),
            "PAGEID": "P0001",
        },
        page_number=0,
    )

    l_web = fileformat.Link(
        {
            "LINKTYPE": "4",
            "LINKINOUT": "0",
            "LINKRECT": "50,60,70,80",
            "LINKTIMESTAMP": "12345",
            "LINKFILE": web_url_b64,
            "LINKFILEID": "none",
            "PAGEID": "none",
        },
        page_number=0,
    )

    l_in = fileformat.Link(
        {
            "LINKTYPE": "0",
            "LINKINOUT": "1",  # DIRECTION_IN (should be ignored)
            "LINKRECT": "10,20,30,40",
            "LINKTIMESTAMP": "12345",
            "LINKFILE": "test.note",
            "LINKFILEID": "none",
            "PAGEID": "none",
        },
        page_number=0,
    )

    l_other_page = fileformat.Link(
        {
            "LINKTYPE": "0",
            "LINKINOUT": "0",
            "LINKRECT": "10,20,30,40",
            "LINKTIMESTAMP": "12345",
            "LINKFILE": "test.note",
            "LINKFILEID": str(sample_notebook.get_fileid()),
            "PAGEID": "P0001",
        },
        page_number=99,
    )

    sample_notebook.links = [l_internal, l_web, l_in, l_other_page]

    pdf_converter = PdfConverter(sample_notebook)
    pdf_bytes = pdf_converter.convert(0, enable_link=True)
    assert pdf_bytes.startswith(b"%PDF-")


def test_single_page_load_and_convert() -> None:
    """Verify loading a single page with page_number loads only that page's bitmaps and produces identical PNG output."""
    full_nb = load_notebook(str(ONE_TO_TEN_NOTE_PATH))
    full_converter = ImageConverter(full_nb)

    target_page = 3
    single_nb = load_notebook(str(ONE_TO_TEN_NOTE_PATH), page_number=target_page)
    single_converter = ImageConverter(single_nb)

    full_img = full_converter.convert(target_page)
    single_img = single_converter.convert(target_page)

    assert full_img.tobytes() == single_img.tobytes()

    with pytest.raises(ValueError, match="out of range"):
        load_notebook(str(ONE_TO_TEN_NOTE_PATH), page_number=999)

    with pytest.raises(ValueError, match="loaded with only page_number=3"):
        single_converter.convert(0)
