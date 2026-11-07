#!/usr/bin/env python3
"""Generate deterministic Bullet Journal `.note` fixtures for OCR evaluation.

Creates valid Supernote `.note` files (`SN_FILE_VER_20260016`) under
`evals/ocr/notebooks/` with `RATTA_RLE`-compressed dot-grid / lined background
layers and anti-aliased `MAINLAYER` handwriting + hand-drawn Rapid Logging
signifiers (`•`, `X`, `>`, `<`, `o`, `-`, `*`, nested indentation, and
`~~strikethrough~~`).
"""

from __future__ import annotations

import copy
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from supernote.notebook import ImageConverter, load_notebook  # noqa: E402
from supernote.notebook.encoder import RattaRleEncoder  # noqa: E402
from supernote.notebook.manipulator import reconstruct  # noqa: E402
from supernote.notebook.schema import LayerName  # noqa: E402

PAGE_WIDTH = 1404
PAGE_HEIGHT = 1872
_RLE_ENCODER = RattaRleEncoder()

HANDWRITING_FONT_CANDIDATES: dict[str, list[str]] = {
    "bradley": [
        "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
        "/System/Library/Fonts/Noteworthy.ttc",
    ],
    "noteworthy": [
        "/System/Library/Fonts/Noteworthy.ttc",
        "/System/Library/Fonts/Supplemental/ChalkboardSE.ttc",
    ],
    "chalkboard": [
        "/System/Library/Fonts/Supplemental/ChalkboardSE.ttc",
        "/System/Library/Fonts/MarkerFelt.ttc",
    ],
}


@dataclass(frozen=True)
class BujoLine:
    """Single line specification on a synthetic Bullet Journal page."""

    text: str
    bullet: str | None = None  # "•", "X", ">", "<", "o", "-", or None (header/blank)
    starred: bool = False
    indent: int = 0
    strikethrough: bool = False
    is_header: bool = False


@dataclass(frozen=True)
class BujoPageSpec:
    """Specification for a single Bullet Journal `.note` page."""

    page_id: str
    background: str  # "dots" or "lined"
    font_style: str
    font_size: int
    seed: int
    lines: tuple[BujoLine, ...]


def _build_background_rle(kind: str) -> bytes:
    """Create a 5mm dot-grid or ruled-line background layer encoded with `RATTA_RLE`."""
    img = Image.new("L", (PAGE_WIDTH, PAGE_HEIGHT), 255)
    draw = ImageDraw.Draw(img)
    if kind == "dots":
        spacing = 58
        for y in range(90, PAGE_HEIGHT - 60, spacing):
            for x in range(72, PAGE_WIDTH - 60, spacing):
                draw.rectangle((x, y, x + 2, y + 2), fill=185)
    elif kind == "lined":
        for y in range(154, PAGE_HEIGHT - 80, 68):
            draw.line((80, y, PAGE_WIDTH - 80, y), fill=185, width=2)
    else:
        raise ValueError(f"Unknown background kind: {kind!r}")
    return _RLE_ENCODER.encode(img, white_is_transparent=False)


def _load_font(style: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in HANDWRITING_FONT_CANDIDATES.get(style, []):
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default(size=size)


def _wobbly_line(
    draw: ImageDraw.ImageDraw,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    rng: random.Random,
    *,
    width: int = 4,
    fill: int = 20,
) -> None:
    """Draw a two-segment slightly curved hand stroke between `(x0, y0)` and `(x1, y1)`."""
    mx = (x0 + x1) / 2.0 + rng.uniform(-2.0, 2.0)
    my = (y0 + y1) / 2.0 + rng.uniform(-2.0, 2.0)
    draw.line([(x0, y0), (mx, my), (x1, y1)], fill=fill, width=width, joint="curve")


def _draw_star(
    draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, rng: random.Random
) -> None:
    """Draw a hand-drawn 6-ray asterisk / star signifier around `(cx, cy)`."""
    for angle_deg in (0, 60, 120):
        rad = math.radians(angle_deg + rng.uniform(-5.0, 5.0))
        dx = math.cos(rad) * r
        dy = math.sin(rad) * r
        _wobbly_line(draw, cx - dx, cy - dy, cx + dx, cy + dy, rng, width=4, fill=25)


def _draw_bullet(
    draw: ImageDraw.ImageDraw,
    bullet: str,
    cx: float,
    cy: float,
    rng: random.Random,
) -> None:
    """Draw a hand-drawn Rapid Logging bullet symbol centered around `(cx, cy)`."""
    if bullet == "•":
        rx = rng.uniform(6.5, 8.0)
        ry = rng.uniform(6.5, 8.0)
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=20)
    elif bullet == "X":
        s = 12.0
        _wobbly_line(draw, cx - s, cy - s, cx + s, cy + s, rng, width=5)
        _wobbly_line(draw, cx - s, cy + s, cx + s, cy - s, rng, width=5)
    elif bullet == ">":
        s = 12.0
        _wobbly_line(draw, cx - s * 0.7, cy - s, cx + s * 0.8, cy, rng, width=5)
        _wobbly_line(draw, cx + s * 0.8, cy, cx - s * 0.7, cy + s, rng, width=5)
    elif bullet == "<":
        s = 12.0
        _wobbly_line(draw, cx + s * 0.7, cy - s, cx - s * 0.8, cy, rng, width=5)
        _wobbly_line(draw, cx - s * 0.8, cy, cx + s * 0.7, cy + s, rng, width=5)
    elif bullet == "o":
        r = 10.5
        pts: list[tuple[float, float]] = []
        for step in range(15):
            ang = (2.0 * math.pi * step) / 14.0
            jr = r + rng.uniform(-1.3, 1.3)
            pts.append((cx + math.cos(ang) * jr, cy + math.sin(ang) * jr))
        draw.line(pts, fill=25, width=4, joint="curve")
    elif bullet == "-":
        s = 12.0
        _wobbly_line(draw, cx - s, cy, cx + s, cy, rng, width=5)
    else:
        raise ValueError(f"Unsupported Rapid Logging bullet: {bullet!r}")


def _render_main_layer_rle(spec: BujoPageSpec) -> bytes:
    """Render handwritten text and Rapid Logging signifiers into a `RATTA_RLE` layer."""
    rng = random.Random(spec.seed)
    img = Image.new("L", (PAGE_WIDTH, PAGE_HEIGHT), 255)
    draw = ImageDraw.Draw(img)

    body_font = _load_font(spec.font_style, spec.font_size)
    header_font = _load_font(spec.font_style, int(spec.font_size * 1.18))

    base_x = 135
    indent_px = 62
    y = 112 if spec.background == "dots" else 102
    line_step = 68 if spec.background == "lined" else 66

    for item in spec.lines:
        if not item.text and item.bullet is None:
            y += line_step
            continue

        jitter_y = rng.uniform(-2.5, 2.5)
        x = base_x + item.indent * indent_px + rng.uniform(-2.0, 2.0)
        font = header_font if item.is_header else body_font
        text_x = x + (48 if item.bullet is not None else 0)

        sample_bbox = draw.textbbox((text_x, y + jitter_y), item.text, font=font)
        ink_mid_y = (sample_bbox[1] + sample_bbox[3]) / 2.0
        ink_bottom_y = float(sample_bbox[3])

        if item.starred:
            _draw_star(draw, x - 44, ink_mid_y, 12.0, rng)

        if item.bullet is not None:
            _draw_bullet(draw, item.bullet, x + 12, ink_mid_y, rng)

        # Render words with slight natural horizontal/vertical hand jitter
        cursor_x = text_x
        words = item.text.split(" ")
        space_w = draw.textlength(" ", font=font)
        start_text_x = cursor_x
        for word in words:
            wy = y + jitter_y + rng.uniform(-1.8, 1.8)
            ink = rng.randint(10, 38)
            draw.text((cursor_x, wy), word, fill=ink, font=font)
            cursor_x += (
                draw.textlength(word, font=font) + space_w + rng.uniform(-1.0, 2.5)
            )
        end_text_x = cursor_x - space_w

        if item.is_header:
            uy = ink_bottom_y + 6.0
            _wobbly_line(
                draw, start_text_x, uy, end_text_x + 12, uy, rng, width=4, fill=45
            )

        if item.strikethrough:
            _wobbly_line(
                draw,
                start_text_x - 6,
                ink_mid_y,
                end_text_x + 8,
                ink_mid_y + rng.uniform(-2.5, 2.5),
                rng,
                width=4,
                fill=30,
            )

        if spec.background == "lined":
            y += line_step * (2 if item.is_header else 1)
        else:
            y += line_step + (24 if item.is_header else 0)

    return _RLE_ENCODER.encode(img, white_is_transparent=True)


def build_notebook_bytes(file_id: str, pages: list[BujoPageSpec]) -> bytes:
    """Pack one or more `BujoPageSpec` pages into a valid `SN_FILE_VER_20260016` `.note`."""
    template_path = REPO_ROOT / "tests/testdata/dsummersl/sn2md_20260618.note"
    notebook = load_notebook(str(template_path))
    template_page = copy.deepcopy(notebook.pages[0])

    meta = notebook.metadata
    meta.header.file_id = file_id
    meta.header.final_operation_page = len(pages)

    bg_cache: dict[str, bytes] = {}
    built_pages = []
    for page_spec in pages:
        page = copy.deepcopy(template_page)
        page.metadata.page_id = page_spec.page_id
        page.metadata.style = (
            "style_5mm_dots" if page_spec.background == "dots" else "style_8mm_ruled"
        )
        page.metadata.totalpath_address = 0
        page.totalpath = None

        if page_spec.background not in bg_cache:
            bg_cache[page_spec.background] = _build_background_rle(page_spec.background)

        main_rle = _render_main_layer_rle(page_spec)
        bg_rle = bg_cache[page_spec.background]

        for layer in page.layers:
            if layer.metadata.name == LayerName.MAINLAYER:
                layer.content = main_rle
            elif layer.metadata.name == LayerName.BGLAYER:
                layer.content = bg_rle

        built_pages.append(page)

    notebook.pages = built_pages
    meta.pages = [p.metadata for p in built_pages]
    return reconstruct(notebook)


DAILY_PAGES: list[BujoPageSpec] = [
    BujoPageSpec(
        page_id="P20261107080000DAILYLOGPAGE0001",
        background="dots",
        font_style="bradley",
        font_size=44,
        seed=110701,
        lines=(
            BujoLine("2026-11-07 Friday", is_header=True),
            BujoLine("Review Q4 infrastructure budget", bullet="•", starred=True),
            BujoLine("Send signed lease renewal to landlord", bullet="X"),
            BujoLine("10:30 Design sync with Maya and Leo", bullet="o"),
            BujoLine(
                "Agreed to ship local OCR before embeddings", bullet="-", indent=1
            ),
            BujoLine("Follow up on latency benchmark numbers", bullet="•", indent=1),
            BujoLine("Migrate home NAS backup script to cron", bullet=">"),
            BujoLine("Order replacement Ceramic nibs", bullet="•", strikethrough=True),
            BujoLine("17:45 Strength training session", bullet="o"),
            BujoLine("Deadlift 3x5 at 275 lbs felt solid", bullet="-", indent=1),
            BujoLine("Read two chapters of Designing Data Systems", bullet="•"),
        ),
    ),
    BujoPageSpec(
        page_id="P20261108083000DAILYLOGPAGE0002",
        background="dots",
        font_style="noteworthy",
        font_size=41,
        seed=110802,
        lines=(
            BujoLine("2026-11-08 Saturday", is_header=True),
            BujoLine(
                "Fix SQLite WAL lock timeout in PR #514", bullet="X", starred=True
            ),
            BujoLine("Tag v0.25.0 release candidate", bullet="•"),
            BujoLine("Verify Linux wheel excludes pyobjc extras", bullet="•", indent=1),
            BujoLine("09:00 Farmers market and coffee run", bullet="o"),
            BujoLine("Schedule annual dentist checkup for Dec", bullet="<"),
            BujoLine("Draft blog post on self-hosted e-ink cloud", bullet=">"),
            BujoLine(
                "Cancel unused staging VM instance", bullet="•", strikethrough=True
            ),
            BujoLine("Latency dropped from 920ms to 165ms after warmup", bullet="-"),
        ),
    ),
]

WEEKLY_PAGES: list[BujoPageSpec] = [
    BujoPageSpec(
        page_id="P20261102090000WEEKLYLOGPAGE001",
        background="lined",
        font_style="chalkboard",
        font_size=39,
        seed=110203,
        lines=(
            BujoLine("Week 45: Nov 2 - Nov 8", is_header=True),
            BujoLine(
                "Finalize multi-provider AI config schema", bullet="X", starred=True
            ),
            BujoLine(
                "Benchmark Apple Vision vs Ollama gemma3", bullet="•", starred=True
            ),
            BujoLine("Clean garage workbench and donate boxes", bullet=">"),
            BujoLine("Wed 14:00 Quarterly roadmap review", bullet="o"),
            BujoLine("Keep core container RAM under 160MB", bullet="-", indent=1),
            BujoLine("Book Thanksgiving flights to Seattle", bullet="X"),
            BujoLine(""),
            BujoLine("Weekly Review", is_header=True),
            BujoLine("Shipped named providers and local macOS OCR", bullet="-"),
            BujoLine("Biggest challenge: context switching mid-week", bullet="-"),
            BujoLine("Next week focus: bounded summary chunking", bullet="•"),
        ),
    ),
]

MONTHLY_PAGES: list[BujoPageSpec] = [
    BujoPageSpec(
        page_id="P20261101070000MONTHLYCALPAGE01",
        background="dots",
        font_style="bradley",
        font_size=40,
        seed=110104,
        lines=(
            BujoLine("November 2026", is_header=True),
            BujoLine("1 Sun   Daylight saving time ends", bullet="o"),
            BujoLine("3 Tue   Election day", bullet="o"),
            BujoLine("6 Fri   Release v0.25.0 milestone", bullet="•", starred=True),
            BujoLine("9 Mon   Pediatrician appointment 11:15", bullet="o"),
            BujoLine("14 Sat Trail half marathon in Marin", bullet="o"),
            BujoLine("18 Wed Quarterly tax estimate due", bullet="X"),
            BujoLine("21 Sat Host friendsgiving dinner", bullet="o"),
            BujoLine("26 Thu Thanksgiving family trip", bullet="o"),
            BujoLine("30 Mon Monthly budget and habit retro", bullet="•"),
        ),
    ),
    BujoPageSpec(
        page_id="P20261101070500MONTHLYTASKPAGE2",
        background="dots",
        font_style="noteworthy",
        font_size=40,
        seed=110105,
        lines=(
            BujoLine("November Goals & Task List", is_header=True),
            BujoLine(
                "Complete 12 strength workouts this month", bullet="•", starred=True
            ),
            BujoLine("Publish OCR evaluation suite and docs", bullet="X"),
            BujoLine("Add per-notebook custom vocabulary hints", bullet="•"),
            BujoLine("Harvest keywords from .note metadata", bullet="-", indent=1),
            BujoLine("Upgrade home server UPS battery pack", bullet=">"),
            BujoLine("Move winter camping trip to January", bullet="<"),
            BujoLine(
                "Rewrite legacy mobile sync prototype", bullet="•", strikethrough=True
            ),
            BujoLine("Lesson learned: measure CER before tuning", bullet="-"),
        ),
    ),
]


def main() -> None:
    out_dir = REPO_ROOT / "evals/ocr/notebooks"
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = [
        ("daily.note", "F20261107080000BUJODAILY000001", DAILY_PAGES),
        ("weekly.note", "F20261102090000BUJOWEEKLY00001", WEEKLY_PAGES),
        ("monthly.note", "F20261101070000BUJOMONTHLY0001", MONTHLY_PAGES),
    ]

    for filename, file_id, specs in targets:
        raw_bytes = build_notebook_bytes(file_id, specs)
        out_path = out_dir / filename
        out_path.write_bytes(raw_bytes)

        # Verify round-trip parsing and rendering
        parsed = load_notebook(str(out_path))
        assert parsed.total_pages == len(specs)
        converter = ImageConverter(parsed)  # type: ignore[no-untyped-call]
        for idx in range(len(specs)):
            rendered = converter.convert(idx)  # type: ignore[no-untyped-call]
            assert rendered.size == (PAGE_WIDTH, PAGE_HEIGHT)
        print(
            f"Generated {out_path.relative_to(REPO_ROOT)} "
            f"({len(specs)} page(s), {len(raw_bytes):,} bytes)"
        )


if __name__ == "__main__":
    main()
