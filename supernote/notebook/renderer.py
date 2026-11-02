"""Stationery typography, Bullet Journal Rapid-Logging, and Markdown page renderer.

Design Philosophy
-----------------
Monochrome e-ink screens (Supernote Nomad `1404x1872` and Manta `1920x2560`) look flat
and utilitarian when rendered like an LCD word processor—heavy spreadsheet borders,
default UI fonts, and dark background grids compete directly with foreground ink.

`supernote.notebook.renderer` instead models **print stationery and Bullet Journal
craftsmanship** (inspired by *The Bullet Journalist*, Hobonichi Techo, and
Leuchtturm1917):

1. **Quiet Paper, High-Contrast Ink**:
   `render_background()` draws paper markings in pale `color.GRAY` (`0xC9`)—5mm dot
   grids with subtle `+` micro-crosshairs every 5th step, ruled lines with a vertical
   left signifier gutter, and framed 5mm graph grids—leaving full black (`0x00`)
   exclusively for foreground typography and strokes.
2. **Baseline-Locked Vertical Rhythm**:
   When paired with `ruled`, `dots`, or `grid` paper, `MarkdownRenderer` locks line
   advance to the exact template step (`get_template_line_spacing()`) and calibrates
   the top margin so alphabetic baselines sit directly on each ruled/dot row, while
   preventing orphan section headings at page bottoms.
3. **Curated Bundled Typography (SIL Open Font License 1.1)**:
   - `RenderStyle.STYLIZED`: *Instrument Serif* display titles & italic pull-quotes +
     *Karla* humanist body + tracked *Space Mono* eyebrows, habit headers, `#HASHTAG`
     pills, and `PG · 01` folios.
   - `RenderStyle.HANDWRITING`: *Caveat* variable script (`wght 400..700` modulated per
     word to simulate natural gel-pen pressure) + *Architects Daughter* hand-lettered
     titles, subtle baseline drift, and fineliner flourishes.
   - `RenderStyle.ARCHITECT`: Crisp *Architects Daughter* draftsperson block lettering +
     *Space Mono* technical stamps.
4. **Expose Intrinsic Facts, Not Binary Mechanics**:
   `MarkdownRenderer` knows nothing about `.note` binary offsets or persistence schemas.
   It returns `RenderedPage` values containing a transparent RGBA foreground image plus
   declarative metadata (`text`, `HeadingSpan`, `KeywordSpan`, `LinkSpan`), allowing
   `NotebookAuthor`, CLI tools, or test harnesses to wire TOC entries, keywords, links,
   or OCR ground truth generically.

Supported Markdown & Bullet Journal Grammar
-------------------------------------------
- **Eyebrow / Dateline**: `#### NOV 2026 · COLLECTION 04` (tracked uppercase `Space Mono`)
- **Headings**: `# Title` (display rule), `## Section` (extending horizontal hairline), `### Subhead`
- **Rapid-Logging Bullets**:
  - `- [ ] Task` (open checkbox in `stylized`, center task dot `•` in `handwriting`/`architect`)
  - `- [x] Completed` (checked box in `stylized`, Ryder Carroll `×` over dot in hand-drawn modes)
  - `- [>] Migrated forward` (`>`), `- [<] Scheduled` (`<`)
  - `- [o] Event` (`○` open circle), `- [-] Note` or `– Note` (`–` em/en dash)
- **Margin Signifiers**: Prefix any rapid-log item with `* ` (6-spoke priority asterisk)
  or `! ` (inspiration mark), e.g. `* - [ ] Ship release` or `! - [-] Key insight`, to
  place the signifier cleanly in the left margin gutter.
- **Inline Accents**: `**bold**`, `*italic*`, `~~strikethrough~~`, `==chisel highlight==`,
  `` `code chip` ``, `#hashtag` pills (extracted as `KeywordSpan`), `[label](https://...)`
  web links, and `[Jump](page:2)` internal 1-based page links (`LinkSpan`).
- **Tables & Habit Trackers**: Standard pipe tables render with Swiss booktabs rules;
  narrow day/metric columns containing `.`, `x`, `o`, or `-` automatically render as
  centered Bullet Journal habit-tracker glyphs.
- **Pagination**: Automatic overflow pagination plus explicit `---` or `<!-- pagebreak -->`.
"""

from __future__ import annotations

import functools
import math
import os
import random
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import color, fileformat

_BUNDLED_FONTS_DIR = Path(__file__).parent / "resources" / "fonts"


class RenderStyle(StrEnum):
    """Curated visual aesthetic presets for rendered notebook pages.

    Attributes:
        STYLIZED: Editorial print stationery pairing *Instrument Serif* headings and
            italic pull-quotes with *Karla* body copy and *Space Mono* metadata stamps.
            Defaults to `BGLAYER` (`user_stylized` PNG) in `NotebookAuthor` so human
            pen strokes on `MAINLAYER` never collide with the template.
        HANDWRITING: Fluid gel-pen script using variable-weight *Caveat* (`wght 400..700`),
            *Architects Daughter* headers, organic baseline micro-wave, and hand-drawn
            Ryder Carroll rapid-logging glyphs. Defaults to `MAINLAYER` (`RATTA_RLE`).
        ARCHITECT: Crisp draftsperson block print (*Architects Daughter* + *Space Mono*)
            with hand-ruled technical dividers. Defaults to `MAINLAYER` (`RATTA_RLE`).
    """

    STYLIZED = "stylized"  # Editorial serif + humanist sans + Space Mono stationery
    HANDWRITING = (
        "handwriting"  # Fluid variable-weight Caveat penmanship + fineliner headers
    )
    ARCHITECT = (
        "architect"  # Crisp draftsperson block print (Bullet Journalist aesthetic)
    )


class BackgroundStyle(StrEnum):
    """Built-in procedural stationery paper styles."""

    WHITE = "white"
    DOTS = "dots"
    RULED = "ruled"
    GRID = "grid"


Rect = tuple[int, int, int, int]  # (left, top, width, height)


@dataclass(frozen=True)
class HeadingSpan:
    """Bounding box and metadata for a rendered heading (maps to Supernote TOC Title)."""

    text: str
    level: int
    rect: Rect


@dataclass(frozen=True)
class KeywordSpan:
    """Bounding box and text for an extracted keyword (maps to Supernote Keyword)."""

    keyword: str
    rect: Rect


@dataclass(frozen=True)
class LinkSpan:
    """Bounding box and target for an inline Markdown link (maps to Supernote Link)."""

    label: str
    target: str
    rect: Rect

    @property
    def is_web_link(self) -> bool:
        return self.target.startswith(("http://", "https://"))

    @property
    def target_page_index(self) -> int | None:
        if self.target.startswith("page:"):
            raw = self.target.removeprefix("page:").strip()
            if raw.isdigit() and int(raw) >= 1:
                return int(raw) - 1
        return None

    @property
    def relative_page_offset(self) -> int | None:
        if self.target.startswith("page:"):
            raw = self.target.removeprefix("page:").strip()
            if raw.startswith(("+", "-")) and raw[1:].isdigit():
                return int(raw)
        return None


@dataclass(frozen=True)
class RenderedPage:
    """A rendered transparent RGBA foreground page plus intrinsic layout metadata.

    Attributes:
        image: Transparent `(page_width, page_height)` RGBA foreground image containing
            only ink, pills, callout tints, and rules (paper template is kept separate
            so callers can composite onto `BGLAYER` or encode directly to `MAINLAYER`).
        text: Normalized plain-text ground-truth transcript of the rendered page,
            suitable for OCR/VLM evaluation and full-text indexing tests.
        headings: Pixel bounding boxes and levels (`1..3`) for rendered headings.
        keywords: Pixel bounding boxes and normalized tag names for `#hashtag` tokens.
        links: Pixel bounding boxes and targets (`https://...` or `page:N`) for links.
    """

    image: Image.Image
    text: str
    headings: tuple[HeadingSpan, ...] = ()
    keywords: tuple[KeywordSpan, ...] = ()
    links: tuple[LinkSpan, ...] = ()


# --- Curated Stationery Font Loader ---


class _FontRole(StrEnum):
    DISPLAY_SERIF = "display_serif"
    DISPLAY_SERIF_ITALIC = "display_serif_italic"
    SANS_REGULAR = "sans_regular"
    SANS_BOLD = "sans_bold"
    MONO_REGULAR = "mono_regular"
    MONO_BOLD = "mono_bold"
    SCRIPT_REGULAR = "script_regular"
    SCRIPT_BOLD = "script_bold"
    ARCHITECT = "architect"


@functools.lru_cache(maxsize=256)
def _load_cached_font(
    role: _FontRole,
    px_size: int,
    custom_path_str: str | None,
    quantized_weight: int | None,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if custom_path_str is not None and role not in (
        _FontRole.MONO_REGULAR,
        _FontRole.MONO_BOLD,
    ):
        font = ImageFont.truetype(custom_path_str, size=px_size)
        if quantized_weight is not None:
            _try_set_weight(font, quantized_weight)
        return font

    file_map: dict[_FontRole, tuple[str, int | None]] = {
        _FontRole.DISPLAY_SERIF: ("InstrumentSerif-Regular.ttf", None),
        _FontRole.DISPLAY_SERIF_ITALIC: ("InstrumentSerif-Italic.ttf", None),
        _FontRole.SANS_REGULAR: ("Karla-Variable.ttf", quantized_weight or 410),
        _FontRole.SANS_BOLD: ("Karla-Variable.ttf", quantized_weight or 700),
        _FontRole.MONO_REGULAR: ("SpaceMono-Regular.ttf", None),
        _FontRole.MONO_BOLD: ("SpaceMono-Bold.ttf", None),
        _FontRole.SCRIPT_REGULAR: ("Caveat-Variable.ttf", quantized_weight or 510),
        _FontRole.SCRIPT_BOLD: ("Caveat-Variable.ttf", quantized_weight or 690),
        _FontRole.ARCHITECT: ("ArchitectsDaughter-Regular.ttf", None),
    }

    fname, axis_weight = file_map[role]
    bundled_path = _BUNDLED_FONTS_DIR / fname
    if bundled_path.is_file():
        font = ImageFont.truetype(str(bundled_path), size=px_size)
        if axis_weight is not None:
            _try_set_weight(font, axis_weight)
        return font

    return ImageFont.load_default(size=px_size)


def _load_role_font(
    role: _FontRole,
    size: int,
    *,
    custom_font_path: str | os.PathLike[str] | None = None,
    weight_override: int | None = None,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    px_size = max(10, int(size))
    custom_str = os.fspath(custom_font_path) if custom_font_path is not None else None
    q_weight = round(weight_override / 10) * 10 if weight_override is not None else None
    return _load_cached_font(role, px_size, custom_str, q_weight)


def _try_set_weight(font: ImageFont.FreeTypeFont, weight: int) -> None:
    try:
        axes = font.get_variation_axes()
        if axes:
            raw_min = axes[0].get("minimum")
            raw_max = axes[0].get("maximum")
            lo = int(raw_min) if raw_min is not None else 400
            hi = int(raw_max) if raw_max is not None else 700
            font.set_variation_by_axes([max(lo, min(hi, int(weight)))])
    except (OSError, ValueError, AttributeError):
        pass


def _track_text(text: str, spaces: int = 1) -> str:
    """Apply subtle letter-spacing to uppercase eyebrow/folio labels."""
    sep = " " * spaces
    return sep.join(list(text))


# --- Stationery Paper Templates (Leuchtturm1917 / Hobonichi Calibrated) ---


def get_pagestyle_name(
    background: BackgroundStyle | str,
    *,
    equipment: str = "N6",
    horizontal: bool = False,
) -> str:
    """Return the Supernote PAGESTYLE string for a built-in background template."""
    bg = BackgroundStyle(background)
    prefix = "style_h_" if horizontal else "style_"
    suffix = "_a5x2" if equipment == "N5" else ""
    match bg:
        case BackgroundStyle.WHITE:
            return f"{prefix}white{suffix}"
        case BackgroundStyle.DOTS:
            return f"{prefix}5mm_dots{suffix}"
        case BackgroundStyle.RULED:
            return f"{prefix}8mm_ruled_line{suffix}"
        case BackgroundStyle.GRID:
            return f"{prefix}5mm_grid{suffix}"


def get_template_line_spacing(
    background: BackgroundStyle | str,
    width: int = fileformat.PAGE_WIDTH,
) -> int:
    """Return the vertical grid/rule spacing in pixels for a given background and width."""
    bg = BackgroundStyle(background)
    scale = width / fileformat.PAGE_WIDTH
    if bg == BackgroundStyle.RULED:
        return round(68 * scale)
    return round(56 * scale)


def render_background(
    background: BackgroundStyle | str = BackgroundStyle.WHITE,
    width: int = fileformat.PAGE_WIDTH,
    height: int = fileformat.PAGE_HEIGHT,
) -> Image.Image:
    """Render a calibrated stationery paper template onto an L-mode image.

    Uses whisper-quiet pale gray (`color.GRAY` / `0xD2`) markings so foreground ink
    commands visual hierarchy, matching Hobonichi Techo and Leuchtturm1917 paper.
    """
    bg = BackgroundStyle(background)
    img = Image.new("L", (width, height), color=color.TRANSPARENT)
    if bg == BackgroundStyle.WHITE:
        return img

    draw = ImageDraw.Draw(img)
    scale = width / fileformat.PAGE_WIDTH
    margin_x = round(92 * scale)
    margin_top = round(140 * scale)
    margin_bottom = round(112 * scale)
    quiet_gray = color.GRAY  # 0xC9 (201) — subtle stationery gray

    if bg == BackgroundStyle.DOTS:
        step = get_template_line_spacing(bg, width)
        dot_size = max(1, round(1.5 * scale))
        row_idx = 0
        y = margin_top
        while y <= height - margin_bottom:
            col_idx = 0
            x = margin_x
            while x <= width - margin_x:
                # Every 5th intersection gets a tiny architectural '+' micro-crosshair
                if row_idx % 5 == 0 and col_idx % 5 == 0:
                    arm = max(2, round(2.5 * scale))
                    draw.line([(x - arm, y), (x + arm, y)], fill=quiet_gray, width=1)
                    draw.line([(x, y - arm), (x, y + arm)], fill=quiet_gray, width=1)
                else:
                    draw.rectangle(
                        (x, y, x + dot_size, y + dot_size),
                        fill=quiet_gray,
                    )
                x += step
                col_idx += 1
            y += step
            row_idx += 1
    elif bg == BackgroundStyle.RULED:
        step = get_template_line_spacing(bg, width)
        y = margin_top + step
        while y <= height - margin_bottom:
            draw.line(
                [(margin_x, y), (width - margin_x, y)],
                fill=quiet_gray,
                width=1,
            )
            y += step
        # Subtle vertical signifier margin gutter line (classic Bullet Journal / architect pad)
        gutter_x = margin_x + round(46 * scale)
        draw.line(
            [
                (gutter_x, margin_top + step // 2),
                (gutter_x, y - step + round(8 * scale)),
            ],
            fill=quiet_gray,
            width=1,
        )
    elif bg == BackgroundStyle.GRID:
        step = get_template_line_spacing(bg, width)
        cols = (width - 2 * margin_x) // step
        rows = (height - margin_top - margin_bottom) // step
        max_x = margin_x + cols * step
        max_y = margin_top + rows * step
        for r in range(rows + 1):
            yy = margin_top + r * step
            shade = color.DARK_GRAY if r in (0, rows) else quiet_gray
            draw.line([(margin_x, yy), (max_x, yy)], fill=shade, width=1)
        for c in range(cols + 1):
            xx = margin_x + c * step
            shade = color.DARK_GRAY if c in (0, cols) else quiet_gray
            draw.line([(xx, margin_top), (xx, max_y)], fill=shade, width=1)

    return img


# --- Markdown & Rapid-Logging Grammar ---


@dataclass
class _InlineToken:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    strike: bool = False
    highlight: bool = False
    link_target: str | None = None
    keyword: str | None = None


@dataclass
class _DocBlock:
    kind: str  # heading, eyebrow, paragraph, rapid_item, quote, table, hr, page_break
    text: str = ""
    level: int = 0
    bullet_state: str = "•"  # 'open', 'done', 'migrated', 'scheduled', 'event', 'note', 'bullet', 'ordered'
    signifier: str = ""  # '', '*', '!'
    order_label: str = ""
    rows: list[list[str]] = field(default_factory=list)


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
# Matches rapid-logging markers with optional margin signifier:
# e.g. `- [ ]`, `* - [ ]`, `! - [-]`, `- * [ ]`, `* [ ]`, `- [>]`, `- [<]`, `- [o]`, `- [-]`
_BUJO_BOX_RE = re.compile(
    r"^(\s*)(?:([*!])\s+)?(?:[-*+]\s+)?(?:([*!])\s+)?\[([ xX><oO*\-!])\]\s+(.+?)\s*$"
)
_SIGNIFIER_DASH_RE = re.compile(r"^(\s*)([*!])\s+[-–—+]\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.+?)\s*$")
_EN_DASH_NOTE_RE = re.compile(r"^(\s*)[–—]\s+(.+?)\s*$")
_ORDERED_RE = re.compile(r"^(\s*)(\d+)\.\s+(.+?)\s*$")
_SIGNIFIER_PREFIX_RE = re.compile(r"^([*!])\s+(.+)$")
_INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_HASHTAG_RE = re.compile(r"(?<!\w)#([A-Za-z][A-Za-z0-9_-]{1,31})\b")


def _extract_signifier(text: str) -> tuple[str, str]:
    """Extract leading Bullet Journal margin signifier (`* ` priority or `! ` inspiration)."""
    if m := _SIGNIFIER_PREFIX_RE.match(text):
        return m.group(1), m.group(2).strip()
    return "", text


def _parse_markdown_blocks(markdown: str) -> list[_DocBlock]:
    """Parse Markdown & Bullet Journal Rapid-Logging shorthand into layout blocks."""
    normalized = markdown.replace("\r\n", "\n").replace("\f", "\n---\n")
    normalized = re.sub(r"<!--\s*pagebreak\s*-->", "\n---\n", normalized, flags=re.I)
    lines = normalized.split("\n")

    blocks: list[_DocBlock] = []
    para_buf: list[str] = []
    quote_buf: list[str] = []
    table_buf: list[list[str]] = []

    def flush_para() -> None:
        if para_buf:
            blocks.append(_DocBlock(kind="paragraph", text=" ".join(para_buf).strip()))
            para_buf.clear()

    def flush_quote() -> None:
        if quote_buf:
            blocks.append(_DocBlock(kind="quote", text=" ".join(quote_buf).strip()))
            quote_buf.clear()

    def flush_table() -> None:
        if table_buf:
            blocks.append(_DocBlock(kind="table", rows=list(table_buf)))
            table_buf.clear()

    def flush_all() -> None:
        flush_para()
        flush_quote()
        flush_table()

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            flush_all()
            continue

        if stripped in ("---", "==="):
            flush_all()
            blocks.append(_DocBlock(kind="page_break"))
            continue
        if re.match(r"^(\*{3,}|_{3,})$", stripped):
            flush_all()
            blocks.append(_DocBlock(kind="hr"))
            continue

        if (
            stripped.startswith("|")
            and stripped.endswith("|")
            and stripped.count("|") >= 2
        ):
            flush_para()
            flush_quote()
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.match(r"^:?-{2,}:?$", c) for c in cells if c):
                continue
            table_buf.append(cells)
            continue
        else:
            flush_table()

        if stripped.startswith(">"):
            flush_para()
            quote_buf.append(stripped.lstrip(">").strip())
            continue
        else:
            flush_quote()

        if m_head := _HEADING_RE.match(stripped):
            flush_para()
            lvl = len(m_head.group(1))
            if lvl >= 4:
                # H4..H6 -> Stationery Eyebrow / Dateline stamp (e.g. `#### MON · 02 NOV 2026`)
                blocks.append(
                    _DocBlock(kind="eyebrow", level=lvl, text=m_head.group(2))
                )
            else:
                blocks.append(
                    _DocBlock(kind="heading", level=lvl, text=m_head.group(2))
                )
            continue

        if m_bujo := _BUJO_BOX_RE.match(raw_line):
            flush_para()
            indent = len(m_bujo.group(1)) // 2
            lead_sig = m_bujo.group(2) or m_bujo.group(3) or ""
            marker = m_bujo.group(4).lower()
            inner_sig, body = _extract_signifier(m_bujo.group(5))
            sig = lead_sig or inner_sig
            state_map = {
                " ": "open",
                "x": "done",
                ">": "migrated",
                "<": "scheduled",
                "o": "event",
                "-": "note",
                "*": "open",
                "!": "note",
            }
            if marker == "*" and not sig:
                sig = "*"
            elif marker == "!" and not sig:
                sig = "!"
            blocks.append(
                _DocBlock(
                    kind="rapid_item",
                    level=indent,
                    bullet_state=state_map.get(marker, "open"),
                    signifier=sig,
                    text=body,
                )
            )
            continue

        if m_sig_dash := _SIGNIFIER_DASH_RE.match(raw_line):
            flush_para()
            indent = len(m_sig_dash.group(1)) // 2
            blocks.append(
                _DocBlock(
                    kind="rapid_item",
                    level=indent,
                    bullet_state="note" if m_sig_dash.group(2) == "!" else "bullet",
                    signifier=m_sig_dash.group(2),
                    text=m_sig_dash.group(3),
                )
            )
            continue

        if m_dash := _EN_DASH_NOTE_RE.match(raw_line):
            flush_para()
            indent = len(m_dash.group(1)) // 2
            sig, body = _extract_signifier(m_dash.group(2))
            blocks.append(
                _DocBlock(
                    kind="rapid_item",
                    level=indent,
                    bullet_state="note",
                    signifier=sig,
                    text=body,
                )
            )
            continue

        if m_bul := _BULLET_RE.match(raw_line):
            flush_para()
            indent = len(m_bul.group(1)) // 2
            sig, body = _extract_signifier(m_bul.group(2))
            blocks.append(
                _DocBlock(
                    kind="rapid_item",
                    level=indent,
                    bullet_state="bullet",
                    signifier=sig,
                    text=body,
                )
            )
            continue

        if m_ord := _ORDERED_RE.match(raw_line):
            flush_para()
            indent = len(m_ord.group(1)) // 2
            sig, body = _extract_signifier(m_ord.group(3))
            blocks.append(
                _DocBlock(
                    kind="rapid_item",
                    level=indent,
                    bullet_state="ordered",
                    order_label=f"{m_ord.group(2)}.",
                    signifier=sig,
                    text=body,
                )
            )
            continue

        para_buf.append(stripped)

    flush_all()
    return blocks


_TOKEN_SPLIT_RE = re.compile(
    r"(\[[^\]]+\]\([^)]+\)|==[^=]+==|~~[^~]+~~|\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)"
)


def _tokenize_inline(text: str, *, extract_keywords: bool) -> list[_InlineToken]:
    """Split inline Markdown formatting (including `==highlight==`) into word tokens."""
    tokens: list[_InlineToken] = []
    parts = _TOKEN_SPLIT_RE.split(text)
    for part in parts:
        if not part:
            continue
        bold = False
        italic = False
        code = False
        strike = False
        highlight = False
        link_target: str | None = None
        content = part

        if m_link := _INLINE_LINK_RE.fullmatch(part):
            content = m_link.group(1)
            link_target = m_link.group(2).strip()
        elif part.startswith("==") and part.endswith("==") and len(part) > 4:
            content = part[2:-2]
            highlight = True
        elif part.startswith("~~") and part.endswith("~~") and len(part) > 4:
            content = part[2:-2]
            strike = True
        elif part.startswith("**") and part.endswith("**") and len(part) > 4:
            content = part[2:-2]
            bold = True
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            content = part[1:-1]
            code = True
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            content = part[1:-1]
            italic = True

        # Handle nested **bold** inside ==highlight==
        if (
            highlight
            and content.startswith("**")
            and content.endswith("**")
            and len(content) > 4
        ):
            content = content[2:-2]
            bold = True

        for word in content.split():
            kw: str | None = None
            if extract_keywords and (
                m_kw := _HASHTAG_RE.fullmatch(word.rstrip(".,;:!?"))
            ):
                kw = m_kw.group(1)
            tokens.append(
                _InlineToken(
                    text=word,
                    bold=bold,
                    italic=italic,
                    code=code,
                    strike=strike,
                    highlight=highlight,
                    link_target=link_target,
                    keyword=kw,
                )
            )
    return tokens


def _plain_text_from_tokens(tokens: list[_InlineToken]) -> str:
    return " ".join(t.text for t in tokens)


# --- Fineliner & Supersampled Bullet Journal Glyph Primitives ---


def _draw_hand_line(
    draw: ImageDraw.ImageDraw,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    rng: random.Random,
    *,
    fill: tuple[int, int, int, int] = (0, 0, 0, 255),
    width: int = 2,
    wobble: float = 1.1,
) -> None:
    """Draw a smooth fineliner segment with subtle organic human curve."""
    dist = math.hypot(x1 - x0, y1 - y0)
    steps = max(2, min(28, int(dist / 24)))
    bow = rng.uniform(-wobble, wobble)
    pts: list[tuple[float, float]] = []
    for i in range(steps + 1):
        t = i / steps
        arc = math.sin(math.pi * t) * bow
        micro = rng.uniform(-wobble * 0.22, wobble * 0.22)
        px = x0 + (x1 - x0) * t + micro
        py = y0 + (y1 - y0) * t + arc + micro
        pts.append((px, py))
    draw.line(pts, fill=fill, width=width)


def _draw_supersampled_bujo_glyph(
    canvas: Image.Image,
    cx: int,
    cy: int,
    size: int,
    glyph: str,
    *,
    hand_drawn: bool,
    rng: random.Random,
    ink_shade: int = 0,
) -> None:
    """Render a 2x-supersampled anti-aliased Ryder Carroll Bullet Journal glyph centered at `(cx, cy)`."""
    ss = 2
    box = max(24, size * 2) * ss
    patch = Image.new("RGBA", (box, box), (255, 255, 255, 0))
    d = ImageDraw.Draw(patch)
    mid = box // 2
    stroke = max(3, round(size * 0.13 * ss))
    ink = (ink_shade, ink_shade, ink_shade, 255)
    wob = 1.6 if hand_drawn else 0.0

    def seg(x0: float, y0: float, x1: float, y1: float, w: int = stroke) -> None:
        if hand_drawn:
            _draw_hand_line(d, x0, y0, x1, y1, rng, fill=ink, width=w, wobble=wob)
        else:
            d.line([(x0, y0), (x1, y1)], fill=ink, width=w)

    if glyph == "dot":
        dot_r = max(5, round(size * 0.21 * ss))
        d.ellipse((mid - dot_r, mid - dot_r, mid + dot_r, mid + dot_r), fill=ink)
    elif glyph == "open_box":
        # Minimalist stationery checkbox
        br = max(8, round(size * 0.40 * ss))
        if hand_drawn:
            seg(mid - br, mid - br, mid + br, mid - br)
            seg(mid + br, mid - br, mid + br, mid + br)
            seg(mid + br, mid + br, mid - br, mid + br)
            seg(mid - br, mid + br, mid - br, mid - br)
        else:
            d.rectangle(
                (mid - br, mid - br, mid + br, mid + br), outline=ink, width=stroke
            )
    elif glyph == "done_x":
        # Ryder Carroll completed task 'X' (with tiny center task dot underneath)
        dot_r = max(3, round(size * 0.11 * ss))
        d.ellipse((mid - dot_r, mid - dot_r, mid + dot_r, mid + dot_r), fill=ink)
        arm = max(8, round(size * 0.38 * ss))
        seg(mid - arm, mid - arm, mid + arm, mid + arm, stroke + 1)
        seg(mid - arm, mid + arm, mid + arm, mid - arm, stroke + 1)
    elif glyph == "checked_box":
        br = max(8, round(size * 0.40 * ss))
        d.rectangle(
            (mid - br, mid - br, mid + br, mid + br),
            fill=(28, 28, 28, 255),
            outline=(28, 28, 28, 255),
            width=stroke,
        )
        white = (254, 254, 254, 255)
        d.line(
            [
                (mid - br * 0.52, mid + br * 0.04),
                (mid - br * 0.12, mid + br * 0.46),
                (mid + br * 0.58, mid - br * 0.42),
            ],
            fill=white,
            width=stroke + 1,
        )
    elif glyph == "migrated":
        arm = max(7, round(size * 0.34 * ss))
        seg(mid - arm * 0.65, mid - arm * 0.85, mid + arm * 0.65, mid, stroke + 1)
        seg(mid + arm * 0.65, mid, mid - arm * 0.65, mid + arm * 0.85, stroke + 1)
    elif glyph == "scheduled":
        arm = max(7, round(size * 0.34 * ss))
        seg(mid + arm * 0.65, mid - arm * 0.85, mid - arm * 0.65, mid, stroke + 1)
        seg(mid - arm * 0.65, mid, mid + arm * 0.65, mid + arm * 0.85, stroke + 1)
    elif glyph == "event":
        cr = max(7, round(size * 0.31 * ss))
        d.ellipse((mid - cr, mid - cr, mid + cr, mid + cr), outline=ink, width=stroke)
    elif glyph == "note":
        arm = max(7, round(size * 0.34 * ss))
        seg(mid - arm, mid, mid + arm, mid, stroke)
    elif glyph == "star":
        # Crisp 6-spoke priority asterisk in the left signifier margin
        arm = max(7, round(size * 0.34 * ss))
        for angle_deg in (0, 60, 120):
            rad = math.radians(angle_deg)
            dx = math.cos(rad) * arm
            dy = math.sin(rad) * arm
            seg(mid - dx, mid - dy, mid + dx, mid + dy, max(2, stroke - 1))
    elif glyph == "bang":
        arm = max(8, round(size * 0.38 * ss))
        seg(mid, mid - arm, mid, mid + arm * 0.28, stroke + 1)
        dot_r = max(2, stroke // 2 + 1)
        d.ellipse(
            (
                mid - dot_r,
                mid + int(arm * 0.68) - dot_r,
                mid + dot_r,
                mid + int(arm * 0.68) + dot_r,
            ),
            fill=ink,
        )

    down = patch.resize((box // ss, box // ss), resample=Image.Resampling.LANCZOS)
    canvas.alpha_composite(
        down, dest=(max(0, cx - down.width // 2), max(0, cy - down.height // 2))
    )


def _draw_highlighter_swipe(
    canvas: Image.Image,
    left: int,
    top: int,
    width: int,
    height: int,
    *,
    hand_drawn: bool,
    rng: random.Random,
    shade: int = 218,
) -> None:
    """Draw a soft monochrome chisel-tip highlighter band onto a tight local patch."""
    pad_x = 8
    slant = 6 if hand_drawn else 0
    jitter = round(rng.uniform(-1.5, 1.5)) if hand_drawn else 0
    band_top = top + round(height * 0.30)
    band_bot = top + round(height * 0.94)
    if band_bot <= band_top or width <= 0:
        return

    x0 = max(0, left - pad_x - slant)
    y0 = max(0, band_top - abs(jitter) - 2)
    x1 = min(canvas.width, left + width + pad_x + slant + 2)
    y1 = min(canvas.height, band_bot + abs(jitter) + 2)
    if x1 <= x0 or y1 <= y0:
        return

    patch = Image.new("RGBA", (x1 - x0, y1 - y0), (255, 255, 255, 0))
    od = ImageDraw.Draw(patch)
    poly = [
        (left - pad_x + slant - x0, band_top + jitter - y0),
        (left + width + pad_x + slant - x0, band_top - jitter - y0),
        (left + width + pad_x - slant - x0, band_bot + jitter - y0),
        (left - pad_x - slant - x0, band_bot - jitter - y0),
    ]
    od.polygon(poly, fill=(shade, shade, shade, 255))
    canvas.alpha_composite(patch, dest=(x0, y0))


def _render_pen_word(
    word: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    rng: random.Random,
    *,
    ink_shade: int = 0,
    angle_deg: float = 0.8,
) -> tuple[Image.Image, int, int]:
    """Render a word onto a transparent RGBA patch preserving its exact font baseline."""
    dummy = Image.new("RGBA", (8, 8), (255, 255, 255, 0))
    d = ImageDraw.Draw(dummy)
    bbox = d.textbbox((0, 0), word, font=font)
    raw_w = max(4, int(bbox[2] - bbox[0]))
    raw_h = max(4, int(bbox[3]))
    pad_x = 10
    pad_y = 8

    patch = Image.new(
        "RGBA", (raw_w + pad_x * 2, raw_h + pad_y * 2), (255, 255, 255, 0)
    )
    pd = ImageDraw.Draw(patch)
    pd.text(
        (pad_x - int(bbox[0]), pad_y),
        word,
        font=font,
        fill=(ink_shade, ink_shade, ink_shade, 255),
    )
    if angle_deg > 0:
        angle = rng.uniform(-angle_deg, angle_deg)
        patch = patch.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)
    return patch, raw_w, raw_h


# --- Main Editorial & Bullet Journal Renderer ---


@dataclass
class _PageBuffer:
    canvas: Image.Image
    draw: ImageDraw.ImageDraw
    cursor_y: int
    text_lines: list[str] = field(default_factory=list)
    headings: list[HeadingSpan] = field(default_factory=list)
    keywords: list[KeywordSpan] = field(default_factory=list)
    links: list[LinkSpan] = field(default_factory=list)
    has_content: bool = False


@dataclass
class _PaginationState:
    page_width: int
    page_height: int
    margin_top: int
    margin_bottom: int
    current: _PageBuffer
    completed: list[_PageBuffer] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        page_width: int,
        page_height: int,
        margin_top: int,
        margin_bottom: int,
    ) -> _PaginationState:
        canvas = Image.new("RGBA", (page_width, page_height), (255, 255, 255, 0))
        buf = _PageBuffer(
            canvas=canvas,
            draw=ImageDraw.Draw(canvas),
            cursor_y=margin_top,
        )
        return cls(
            page_width=page_width,
            page_height=page_height,
            margin_top=margin_top,
            margin_bottom=margin_bottom,
            current=buf,
        )

    def flush_page(self) -> None:
        self.completed.append(self.current)
        canvas = Image.new(
            "RGBA", (self.page_width, self.page_height), (255, 255, 255, 0)
        )
        self.current = _PageBuffer(
            canvas=canvas,
            draw=ImageDraw.Draw(canvas),
            cursor_y=self.margin_top,
        )

    def ensure_space(self, needed_h: int) -> bool:
        if (
            self.current.has_content
            and self.current.cursor_y + needed_h > self.page_height - self.margin_bottom
        ):
            self.flush_page()
            return True
        return False


class MarkdownRenderer:
    """Stateful layout engine that paginates Markdown into `RenderedPage` bitmaps.

    `MarkdownRenderer` is deterministic for a fixed `seed`, making simulated handwriting
    jitter, optical pen-pressure variation, and fineliner wobble 100% reproducible
    across test runs.
    """

    def __init__(
        self,
        *,
        style: RenderStyle | str = RenderStyle.STYLIZED,
        background: BackgroundStyle | str = BackgroundStyle.WHITE,
        page_width: int = fileformat.PAGE_WIDTH,
        page_height: int = fileformat.PAGE_HEIGHT,
        font_path: str | os.PathLike[str] | None = None,
        font_size: int | None = None,
        seed: int = 0,
        extract_keywords: bool = True,
        show_page_furniture: bool = True,
    ) -> None:
        """Configure page geometry, stationery preset, and line-grid calibration.

        Args:
            style: Typography preset (`"stylized"`, `"handwriting"`, or `"architect"`).
            background: Paper template whose vertical grid spacing calibrates `line_height`
                (`"white"`, `"dots"`, `"ruled"`, or `"grid"`).
            page_width: Canvas width in pixels (`1404` for Nomad, `1920` for Manta).
            page_height: Canvas height in pixels (`1872` for Nomad, `2560` for Manta).
            font_path: Optional override path to a custom `.ttf`/`.otf` font file.
            font_size: Optional override for base body font size in pixels.
            seed: Deterministic RNG seed for handwriting pressure/jitter.
            extract_keywords: When `True`, parses `#hashtag` tokens into `KeywordSpan` badges.
            show_page_furniture: Stamp subtle top/bottom `PG · 01` / `01 / 02` stationery folios.
        """
        if page_width <= 0 or page_height <= 0:
            raise ValueError(
                f"page_width and page_height must be positive, got {(page_width, page_height)!r}"
            )
        if font_size is not None and font_size <= 0:
            raise ValueError(f"font_size must be positive, got {font_size!r}")

        self.style = RenderStyle(style)
        self.background = BackgroundStyle(background)
        self.page_width = page_width
        self.page_height = page_height
        self.font_path = font_path
        self.seed = seed
        self.extract_keywords = extract_keywords
        self.show_page_furniture = show_page_furniture

        scale = page_width / fileformat.PAGE_WIDTH
        self.scale = scale

        if font_size is not None:
            base_size = font_size
        elif self.style == RenderStyle.HANDWRITING:
            # Caveat has a compact script x-height; 46px reads like natural 0.5mm gel pen
            base_size = round(46 * scale)
        elif self.style == RenderStyle.ARCHITECT:
            base_size = round(33 * scale)
        else:
            base_size = round(32 * scale)

        self.base_font_size = base_size
        self.gutter_w = round(46 * scale)
        # Left margin aligns body/bullets cleanly to the right of the signifier margin gutter
        self.paper_margin_x = round(92 * scale)
        self.margin_x = self.paper_margin_x + self.gutter_w
        self.right_margin_x = self.paper_margin_x
        self.margin_top = round(140 * scale)
        self.margin_bottom = round(118 * scale)

        if self.background in (
            BackgroundStyle.RULED,
            BackgroundStyle.DOTS,
            BackgroundStyle.GRID,
        ):
            grid_step = get_template_line_spacing(self.background, page_width)
            self.line_height = grid_step
            self.margin_top = round(140 * scale) + grid_step - round(base_size * 0.82)
            if self.background == BackgroundStyle.GRID:
                cols = (page_width - 2 * self.paper_margin_x) // grid_step
                grid_max_x = self.paper_margin_x + cols * grid_step
                self.right_margin_x = page_width - grid_max_x
        else:
            self.line_height = round(
                base_size * (1.36 if self.style == RenderStyle.HANDWRITING else 1.62)
            )

    @property
    def _is_hand_drawn(self) -> bool:
        return self.style in (RenderStyle.HANDWRITING, RenderStyle.ARCHITECT)

    def _snap_to_grid(self, y: int) -> int:
        if self.background in (
            BackgroundStyle.RULED,
            BackgroundStyle.DOTS,
            BackgroundStyle.GRID,
        ):
            offset = y - self.margin_top
            if offset > 0:
                steps = math.ceil(offset / self.line_height)
                return self.margin_top + steps * self.line_height
        return y

    def render(self, markdown: str) -> list[RenderedPage]:
        """Render a Markdown string into one or more `RenderedPage` objects."""
        rng = random.Random(self.seed)
        blocks = _parse_markdown_blocks(markdown)
        state = _PaginationState.create(
            page_width=self.page_width,
            page_height=self.page_height,
            margin_top=self.margin_top,
            margin_bottom=self.margin_bottom,
        )

        doc_title = next(
            (b.text for b in blocks if b.kind == "heading" and b.level == 1),
            "",
        )

        for block in blocks:
            if block.kind == "page_break":
                state.flush_page()
            elif block.kind == "hr":
                self._render_hr_block(state, rng)
            elif block.kind == "eyebrow":
                self._render_eyebrow_block(state, block)
            elif block.kind == "heading":
                self._render_heading_block(state, block, rng)
            elif block.kind == "table":
                self._render_table_block(state, block, rng)
            elif block.kind == "quote":
                self._render_quote_block(state, block, rng)
            elif block.kind == "rapid_item":
                self._render_rapid_item_block(state, block, rng)
            else:
                self._render_paragraph_block(state, block, rng)

        if state.current.has_content or not state.completed:
            state.flush_page()

        total_pages = len(state.completed)
        final_pages: list[RenderedPage] = []
        for idx, pg in enumerate(state.completed):
            if self.show_page_furniture:
                self._stamp_page_furniture(
                    pg.canvas,
                    page_num=idx + 1,
                    total_pages=total_pages,
                    running_title=doc_title,
                    is_first_page=(idx == 0),
                )
            final_pages.append(
                RenderedPage(
                    image=pg.canvas,
                    text="\n".join(pg.text_lines).strip(),
                    headings=tuple(pg.headings),
                    keywords=tuple(pg.keywords),
                    links=tuple(pg.links),
                )
            )
        return final_pages

    def _render_hr_block(self, state: _PaginationState, rng: random.Random) -> None:
        state.ensure_space(self.line_height)
        page = state.current
        full_left = self.paper_margin_x
        full_right = self.page_width - self.right_margin_x
        mid_y = page.cursor_y + self.line_height // 2

        if self._is_hand_drawn:
            center_x = (full_left + full_right) // 2
            wing = round(220 * self.scale)
            _draw_hand_line(
                page.draw,
                center_x - wing,
                mid_y,
                center_x - round(26 * self.scale),
                mid_y,
                rng,
                fill=(color.DARK_GRAY, color.DARK_GRAY, color.DARK_GRAY, 255),
                width=max(2, round(2 * self.scale)),
            )
            _draw_supersampled_bujo_glyph(
                page.canvas,
                center_x,
                mid_y,
                round(22 * self.scale),
                "dot",
                hand_drawn=True,
                rng=rng,
                ink_shade=color.DARK_GRAY,
            )
            _draw_hand_line(
                page.draw,
                center_x + round(26 * self.scale),
                mid_y,
                center_x + wing,
                mid_y,
                rng,
                fill=(color.DARK_GRAY, color.DARK_GRAY, color.DARK_GRAY, 255),
                width=max(2, round(2 * self.scale)),
            )
        else:
            page.draw.line(
                [(full_left, mid_y), (full_right, mid_y)],
                fill=(185, 185, 185, 255),
                width=max(1, round(1.5 * self.scale)),
            )
        page.cursor_y = self._snap_to_grid(page.cursor_y + self.line_height)
        page.has_content = True

    def _render_eyebrow_block(self, state: _PaginationState, block: _DocBlock) -> None:
        mono_f = _load_role_font(
            _FontRole.MONO_BOLD,
            round(20 * self.scale),
            custom_font_path=None,
        )
        label = _track_text(block.text.upper(), spaces=1)
        step_h = round(38 * self.scale)
        state.ensure_space(step_h)
        page = state.current
        page.draw.text(
            (self.paper_margin_x, page.cursor_y),
            label,
            font=mono_f,
            fill=(105, 105, 105, 255),
        )
        page.text_lines.append(block.text)
        page.cursor_y += step_h
        page.has_content = True

    def _render_heading_block(
        self, state: _PaginationState, block: _DocBlock, rng: random.Random
    ) -> None:
        tokens = _tokenize_inline(block.text, extract_keywords=self.extract_keywords)
        plain = _plain_text_from_tokens(tokens)
        full_left = self.paper_margin_x
        full_right = self.page_width - self.right_margin_x
        body_max_w = full_right - self.margin_x

        if block.level == 1:
            h_size = round(
                self.base_font_size
                * (
                    1.58
                    if self.style == RenderStyle.HANDWRITING
                    else 2.15
                    if self.style == RenderStyle.STYLIZED
                    else 1.68
                )
            )
            h_line_h = round(h_size * 1.24)
            if state.current.has_content:
                state.current.cursor_y += round(self.line_height * 0.45)
            state.ensure_space(h_line_h + round(34 * self.scale))
            page = state.current

            rect = self._draw_wrapped_tokens(
                canvas=page.canvas,
                draw=page.draw,
                tokens=tokens,
                x_start=full_left,
                y_start=page.cursor_y,
                max_width=full_right - full_left,
                font_size=h_size,
                line_height=h_line_h,
                heading_level=1,
                default_bold=True,
                rng=rng,
                keywords_out=page.keywords,
                links_out=page.links,
            )
            ul_y = rect[1] + rect[3] + round(6 * self.scale)
            if self.style == RenderStyle.STYLIZED:
                page.draw.line(
                    [(full_left, ul_y), (full_right, ul_y)],
                    fill=(0, 0, 0, 255),
                    width=max(3, round(3 * self.scale)),
                )
                thin_y = ul_y + max(5, round(6 * self.scale))
                page.draw.line(
                    [(full_left, thin_y), (full_right, thin_y)],
                    fill=(150, 150, 150, 255),
                    width=1,
                )
                page.cursor_y = thin_y + round(22 * self.scale)
            else:
                _draw_hand_line(
                    page.draw,
                    full_left,
                    ul_y,
                    full_right,
                    ul_y,
                    rng,
                    fill=(0, 0, 0, 255),
                    width=max(3, round(3.2 * self.scale)),
                    wobble=0.9,
                )
                page.cursor_y = ul_y + round(20 * self.scale)
        elif block.level == 2:
            h_size = round(
                self.base_font_size
                * (
                    1.22
                    if self.style == RenderStyle.HANDWRITING
                    else 0.88
                    if self.style == RenderStyle.STYLIZED
                    else 1.12
                )
            )
            h_line_h = round(max(h_size * 1.4, self.line_height * 0.9))
            if state.current.has_content:
                state.current.cursor_y += round(self.line_height * 0.42)
            state.current.cursor_y = self._snap_to_grid(state.current.cursor_y)
            state.ensure_space(h_line_h + self.line_height * 2)
            page = state.current

            display_tokens = (
                [
                    _InlineToken(
                        text=t.text.upper(),
                        bold=True,
                        keyword=t.keyword,
                        link_target=t.link_target,
                    )
                    for t in tokens
                ]
                if self.style in (RenderStyle.STYLIZED, RenderStyle.ARCHITECT)
                else tokens
            )

            if self.style == RenderStyle.HANDWRITING:
                est_f = _load_role_font(
                    _FontRole.SCRIPT_BOLD, h_size, custom_font_path=self.font_path
                )
                est_box = page.draw.textbbox((0, 0), plain, font=est_f)
                _draw_highlighter_swipe(
                    page.canvas,
                    full_left,
                    page.cursor_y,
                    min(full_right - full_left, int(est_box[2] - est_box[0]) + 16),
                    h_size,
                    hand_drawn=True,
                    rng=rng,
                    shade=226,
                )

            rect = self._draw_wrapped_tokens(
                canvas=page.canvas,
                draw=page.draw,
                tokens=display_tokens,
                x_start=full_left,
                y_start=page.cursor_y,
                max_width=full_right - full_left,
                font_size=h_size,
                line_height=h_line_h,
                heading_level=2,
                default_bold=True,
                rng=rng,
                keywords_out=page.keywords,
                links_out=page.links,
            )
            rule_start = rect[0] + rect[2] + round(22 * self.scale)
            mid_rule_y = rect[1] + round(h_size * 0.62)
            if rule_start + round(60 * self.scale) < full_right:
                if self._is_hand_drawn:
                    _draw_hand_line(
                        page.draw,
                        rule_start,
                        mid_rule_y,
                        full_right,
                        mid_rule_y,
                        rng,
                        fill=(165, 165, 165, 255),
                        width=max(1, round(1.6 * self.scale)),
                        wobble=0.7,
                    )
                else:
                    page.draw.line(
                        [(rule_start, mid_rule_y), (full_right, mid_rule_y)],
                        fill=(175, 175, 175, 255),
                        width=max(1, round(1.5 * self.scale)),
                    )
            page.cursor_y = rect[1] + rect[3] + round(6 * self.scale)
        else:
            h_size = round(self.base_font_size * 1.08)
            h_line_h = round(h_size * 1.38)
            if state.current.has_content:
                state.current.cursor_y += round(self.line_height * 0.25)
            state.current.cursor_y = self._snap_to_grid(state.current.cursor_y)
            state.ensure_space(h_line_h)
            page = state.current
            rect = self._draw_wrapped_tokens(
                canvas=page.canvas,
                draw=page.draw,
                tokens=tokens,
                x_start=self.margin_x,
                y_start=page.cursor_y,
                max_width=body_max_w,
                font_size=h_size,
                line_height=h_line_h,
                heading_level=3,
                default_bold=True,
                rng=rng,
                keywords_out=page.keywords,
                links_out=page.links,
            )
            page.cursor_y = rect[1] + rect[3] + round(4 * self.scale)

        page.cursor_y = self._snap_to_grid(page.cursor_y)
        page.headings.append(HeadingSpan(text=plain, level=block.level, rect=rect))
        page.text_lines.append(plain)
        page.has_content = True

    def _draw_table_top_rule(
        self,
        page: _PageBuffer,
        full_left: int,
        actual_right: int,
        y: int,
        rng: random.Random,
    ) -> None:
        if self._is_hand_drawn:
            _draw_hand_line(
                page.draw,
                full_left,
                y,
                actual_right,
                y,
                rng,
                fill=(0, 0, 0, 255),
                width=max(2, round(2.6 * self.scale)),
                wobble=0.7,
            )
        else:
            page.draw.line(
                [(full_left, y), (actual_right, y)],
                fill=(0, 0, 0, 255),
                width=max(2, round(2.6 * self.scale)),
            )

    def _draw_table_row(
        self,
        page: _PageBuffer,
        row: list[str],
        *,
        num_cols: int,
        col_starts: list[int],
        col_widths: list[int],
        full_left: int,
        actual_right: int,
        row_h: int,
        is_tracker: bool,
        is_header: bool,
        is_last: bool,
        record_text: bool,
        rng: random.Random,
    ) -> None:
        row_top = page.cursor_y
        row_bottom = row_top + row_h
        if is_header:
            page.draw.rectangle(
                (full_left, row_top + 2, actual_right, row_bottom - 1),
                fill=(242, 242, 242, 255),
            )

        glyph_map = {
            ".": "dot",
            "·": "dot",
            "[ ]": "dot",
            "x": "done_x",
            "X": "done_x",
            "[x]": "done_x",
            "[X]": "done_x",
            "o": "event",
            "O": "event",
            "-": "note",
        }

        for c_idx in range(num_cols):
            cell_val = row[c_idx].strip() if c_idx < len(row) else ""
            c_left = col_starts[c_idx]
            c_w = col_widths[c_idx]
            cx = c_left + c_w // 2
            cy = row_top + row_h // 2

            if not is_header and c_idx > 0 and cell_val in glyph_map:
                shade = 175 if cell_val in (".", "·", "[ ]") else 0
                _draw_supersampled_bujo_glyph(
                    page.canvas,
                    cx,
                    cy,
                    round(24 * self.scale),
                    glyph_map[cell_val],
                    hand_drawn=self._is_hand_drawn,
                    rng=rng,
                    ink_shade=shade,
                )
                continue

            if is_header:
                hdr_font = _load_role_font(
                    _FontRole.MONO_BOLD,
                    round(20 * self.scale),
                    custom_font_path=None,
                )
                label = cell_val.upper()
                hb = page.draw.textbbox((0, 0), label, font=hdr_font)
                hw = int(hb[2] - hb[0])
                hh = int(hb[3] - hb[1])
                hx = (
                    cx - hw // 2
                    if (is_tracker and c_idx > 0)
                    else c_left + round(10 * self.scale)
                )
                hy = row_top + (row_h - hh) // 2 - int(hb[1]) // 2
                page.draw.text((hx, hy), label, font=hdr_font, fill=(20, 20, 20, 255))
            else:
                tokens = _tokenize_inline(
                    cell_val, extract_keywords=self.extract_keywords
                )
                cell_font_sz = round(self.base_font_size * 0.88)
                self._draw_wrapped_tokens(
                    canvas=page.canvas,
                    draw=page.draw,
                    tokens=tokens,
                    x_start=c_left + round(10 * self.scale),
                    y_start=row_top + round((row_h - cell_font_sz) * 0.35),
                    max_width=max(32, c_w - round(20 * self.scale)),
                    font_size=cell_font_sz,
                    line_height=row_h,
                    default_bold=False,
                    rng=rng,
                    keywords_out=page.keywords if record_text else [],
                    links_out=page.links if record_text else [],
                )

        rule_shade = 0 if (is_header or is_last) else 208
        rule_w = (
            max(2, round(2 * self.scale))
            if is_last
            else (max(1, round(1.5 * self.scale)) if is_header else 1)
        )
        if self._is_hand_drawn and (is_header or is_last):
            _draw_hand_line(
                page.draw,
                full_left,
                row_bottom,
                actual_right,
                row_bottom,
                rng,
                fill=(rule_shade, rule_shade, rule_shade, 255),
                width=rule_w,
                wobble=0.7,
            )
        else:
            page.draw.line(
                [(full_left, row_bottom), (actual_right, row_bottom)],
                fill=(rule_shade, rule_shade, rule_shade, 255),
                width=rule_w,
            )

        if record_text:
            page.text_lines.append(" | ".join(row))
        page.cursor_y = row_bottom
        page.has_content = True

    def _render_table_block(
        self, state: _PaginationState, block: _DocBlock, rng: random.Random
    ) -> None:
        if not block.rows:
            return
        full_left = self.paper_margin_x
        full_right = self.page_width - self.right_margin_x
        num_cols = max((len(r) for r in block.rows), default=1)
        table_w = full_right - full_left
        is_tracker = (
            num_cols >= 4
            and len(block.rows) >= 2
            and all(len(c) <= 3 for c in block.rows[0][1:])
        )
        if is_tracker:
            first_col_w = round(table_w * 0.38)
            other_w = (table_w - first_col_w) // (num_cols - 1)
            col_widths = [first_col_w] + [other_w] * (num_cols - 1)
        else:
            cw = table_w // max(1, num_cols)
            col_widths = [cw] * num_cols

        col_starts = [full_left]
        for cw in col_widths[:-1]:
            col_starts.append(col_starts[-1] + cw)
        actual_right = col_starts[-1] + col_widths[-1]

        row_h = max(round(52 * self.scale), round(self.line_height * 0.92))
        state.ensure_space(
            min(row_h * len(block.rows) + round(24 * self.scale), self.page_height // 2)
        )
        if state.current.has_content:
            state.current.cursor_y += round(8 * self.scale)

        self._draw_table_top_rule(
            state.current, full_left, actual_right, state.current.cursor_y, rng
        )

        for r_idx, row in enumerate(block.rows):
            if (
                state.current.has_content
                and state.current.cursor_y + row_h
                > self.page_height - self.margin_bottom
            ):
                state.flush_page()
                self._draw_table_top_rule(
                    state.current, full_left, actual_right, state.current.cursor_y, rng
                )
                if r_idx > 0 and len(block.rows) >= 2:
                    self._draw_table_row(
                        state.current,
                        block.rows[0],
                        num_cols=num_cols,
                        col_starts=col_starts,
                        col_widths=col_widths,
                        full_left=full_left,
                        actual_right=actual_right,
                        row_h=row_h,
                        is_tracker=is_tracker,
                        is_header=True,
                        is_last=False,
                        record_text=False,
                        rng=rng,
                    )

            self._draw_table_row(
                state.current,
                row,
                num_cols=num_cols,
                col_starts=col_starts,
                col_widths=col_widths,
                full_left=full_left,
                actual_right=actual_right,
                row_h=row_h,
                is_tracker=is_tracker,
                is_header=(r_idx == 0),
                is_last=(r_idx == len(block.rows) - 1),
                record_text=True,
                rng=rng,
            )

        state.current.cursor_y = self._snap_to_grid(
            state.current.cursor_y + round(self.line_height * 0.45)
        )

    def _render_quote_block(
        self, state: _PaginationState, block: _DocBlock, rng: random.Random
    ) -> None:
        tokens = _tokenize_inline(block.text, extract_keywords=self.extract_keywords)
        plain = _plain_text_from_tokens(tokens)
        full_left = self.paper_margin_x
        full_right = self.page_width - self.right_margin_x
        quote_w = max(64, full_right - full_left)
        pad_x = round(34 * self.scale)
        pad_y = round(16 * self.scale)
        q_size = round(
            self.base_font_size * (1.22 if self.style == RenderStyle.STYLIZED else 1.02)
        )
        q_line_h = round(
            q_size * (1.35 if self.style == RenderStyle.STYLIZED else 1.42)
        )
        state.ensure_space(q_line_h + pad_y * 2)
        page = state.current
        quote_top = page.cursor_y

        max_strip_h = max(q_line_h * 4 + pad_y * 2, self.page_height - quote_top)
        temp_fg = Image.new("RGBA", (quote_w, max_strip_h), (255, 255, 255, 0))
        temp_draw = ImageDraw.Draw(temp_fg)
        local_kws: list[KeywordSpan] = []
        local_links: list[LinkSpan] = []

        rect = self._draw_wrapped_tokens(
            canvas=temp_fg,
            draw=temp_draw,
            tokens=tokens,
            x_start=pad_x,
            y_start=pad_y,
            max_width=max(48, quote_w - pad_x * 2),
            font_size=q_size,
            line_height=q_line_h,
            default_bold=False,
            default_italic=True,
            ink_shade=30,
            rng=rng,
            keywords_out=local_kws,
            links_out=local_links,
        )
        quote_h = rect[1] + rect[3] + pad_y // 2
        quote_bottom = min(self.page_height, quote_top + quote_h)

        if self.style == RenderStyle.STYLIZED:
            page.draw.rectangle(
                (full_left, quote_top, full_right, quote_bottom),
                fill=(245, 245, 245, 255),
            )
            page.draw.line(
                [(full_left, quote_top), (full_left, quote_bottom)],
                fill=(25, 25, 25, 255),
                width=max(4, round(4 * self.scale)),
            )
            page.draw.line(
                [
                    (full_left + round(7 * self.scale), quote_top),
                    (full_left + round(7 * self.scale), quote_bottom),
                ],
                fill=(165, 165, 165, 255),
                width=1,
            )
        else:
            _draw_hand_line(
                page.draw,
                full_left + round(6 * self.scale),
                quote_top + 4,
                full_left + round(6 * self.scale),
                quote_bottom - 4,
                rng,
                fill=(40, 40, 40, 255),
                width=max(3, round(3 * self.scale)),
                wobble=0.9,
            )

        cropped_fg = temp_fg.crop(
            (0, 0, quote_w, min(temp_fg.height, quote_bottom - quote_top + pad_y))
        )
        page.canvas.alpha_composite(cropped_fg, dest=(full_left, quote_top))

        for kw in local_kws:
            r = kw.rect
            page.keywords.append(
                KeywordSpan(
                    keyword=kw.keyword,
                    rect=(r[0] + full_left, r[1] + quote_top, r[2], r[3]),
                )
            )
        for lnk in local_links:
            r = lnk.rect
            page.links.append(
                LinkSpan(
                    label=lnk.label,
                    target=lnk.target,
                    rect=(r[0] + full_left, r[1] + quote_top, r[2], r[3]),
                )
            )

        page.cursor_y = self._snap_to_grid(
            quote_bottom + round(self.line_height * 0.42)
        )
        page.text_lines.append(plain)
        page.has_content = True

    def _render_rapid_item_block(
        self, state: _PaginationState, block: _DocBlock, rng: random.Random
    ) -> None:
        indent_px = block.level * round(42 * self.scale)
        state.ensure_space(self.line_height)
        page = state.current
        full_right = self.page_width - self.right_margin_x

        bullet_cx = self.margin_x + indent_px + round(14 * self.scale)
        text_x = self.margin_x + indent_px + round(40 * self.scale)
        glyph_cy = page.cursor_y + round(
            self.base_font_size
            * (0.62 if self.style == RenderStyle.HANDWRITING else 0.58)
        )
        glyph_sz = round(26 * self.scale)

        if block.signifier:
            sig_cx = self.paper_margin_x + self.gutter_w // 2
            _draw_supersampled_bujo_glyph(
                page.canvas,
                sig_cx,
                glyph_cy,
                round(24 * self.scale),
                "star" if block.signifier == "*" else "bang",
                hand_drawn=self._is_hand_drawn,
                rng=rng,
                ink_shade=0,
            )

        item_state = block.bullet_state
        if item_state == "ordered":
            num_f = _load_role_font(
                _FontRole.MONO_BOLD if not self._is_hand_drawn else _FontRole.ARCHITECT,
                round(
                    self.base_font_size
                    * (0.72 if self.style == RenderStyle.HANDWRITING else 0.82)
                ),
            )
            page.draw.text(
                (self.margin_x + indent_px, page.cursor_y + round(4 * self.scale)),
                block.order_label,
                font=num_f,
                fill=(30, 30, 30, 255),
            )
        else:
            if self.style == RenderStyle.STYLIZED and item_state in ("open", "done"):
                b_glyph = "checked_box" if item_state == "done" else "open_box"
            else:
                b_glyph_map = {
                    "open": "dot",
                    "bullet": "dot",
                    "done": "done_x",
                    "migrated": "migrated",
                    "scheduled": "scheduled",
                    "event": "event",
                    "note": "note",
                }
                b_glyph = b_glyph_map.get(item_state, "dot")
            _draw_supersampled_bujo_glyph(
                page.canvas,
                bullet_cx,
                glyph_cy,
                glyph_sz,
                b_glyph,
                hand_drawn=self._is_hand_drawn,
                rng=rng,
                ink_shade=0,
            )

        tokens = _tokenize_inline(block.text, extract_keywords=self.extract_keywords)
        plain = _plain_text_from_tokens(tokens)
        item_shade = (
            95 if (item_state == "done" and self.style == RenderStyle.STYLIZED) else 0
        )
        rect = self._draw_wrapped_tokens(
            canvas=page.canvas,
            draw=page.draw,
            tokens=tokens,
            x_start=text_x,
            y_start=page.cursor_y,
            max_width=max(100, full_right - text_x),
            font_size=self.base_font_size,
            line_height=self.line_height,
            default_bold=(block.signifier == "*" and not self._is_hand_drawn),
            ink_shade=item_shade,
            rng=rng,
            keywords_out=page.keywords,
            links_out=page.links,
        )

        prefix_map = {
            "open": "[ ]",
            "done": "[x]",
            "migrated": "[>]",
            "scheduled": "[<]",
            "event": "○",
            "note": "–",
            "bullet": "•",
            "ordered": block.order_label,
        }
        gt_prefix = prefix_map.get(item_state, "•")
        page.text_lines.append(f"{gt_prefix} {plain}")
        page.cursor_y = self._snap_to_grid(rect[1] + rect[3])
        page.has_content = True

    def _render_paragraph_block(
        self, state: _PaginationState, block: _DocBlock, rng: random.Random
    ) -> None:
        tokens = _tokenize_inline(block.text, extract_keywords=self.extract_keywords)
        if not tokens:
            return
        plain = _plain_text_from_tokens(tokens)
        state.ensure_space(self.line_height)
        page = state.current
        full_left = self.paper_margin_x
        full_right = self.page_width - self.right_margin_x

        rect = self._draw_wrapped_tokens(
            canvas=page.canvas,
            draw=page.draw,
            tokens=tokens,
            x_start=full_left,
            y_start=page.cursor_y,
            max_width=full_right - full_left,
            font_size=self.base_font_size,
            line_height=self.line_height,
            default_bold=False,
            rng=rng,
            keywords_out=page.keywords,
            links_out=page.links,
        )
        page.text_lines.append(plain)
        page.cursor_y = self._snap_to_grid(
            rect[1] + rect[3] + round(self.line_height * 0.32)
        )
        page.has_content = True

    def _stamp_page_furniture(
        self,
        canvas: Image.Image,
        *,
        page_num: int,
        total_pages: int,
        running_title: str,
        is_first_page: bool,
    ) -> None:
        """Stamp subtle stationery folio (`01 / 02`) and top index marker."""
        draw = ImageDraw.Draw(canvas)
        mono = _load_role_font(_FontRole.MONO_REGULAR, round(18 * self.scale))
        left_x = self.paper_margin_x
        right_x = self.page_width - self.right_margin_x
        top_y = round(64 * self.scale)

        folio_label = (
            f"PG · {page_num:02d}"
            if total_pages == 1
            else f"{page_num:02d} / {total_pages:02d}"
        )
        fb = draw.textbbox((0, 0), folio_label, font=mono)
        fw = int(fb[2] - fb[0])
        draw.text(
            (right_x - fw, top_y),
            folio_label,
            font=mono,
            fill=(135, 135, 135, 255),
        )

        if not is_first_page and running_title:
            trimmed = running_title[:36].upper()
            eyebrow = _track_text(trimmed, spaces=1)
            draw.text(
                (left_x, top_y),
                eyebrow,
                font=mono,
                fill=(150, 150, 150, 255),
            )
            rule_y = top_y + round(28 * self.scale)
            draw.line(
                [(left_x, rule_y), (right_x, rule_y)],
                fill=(210, 210, 210, 255),
                width=1,
            )

        # Bottom centered subtle index dot/folio
        bot_y = self.page_height - round(66 * self.scale)
        bot_str = f"— {page_num:02d} —"
        bb = draw.textbbox((0, 0), bot_str, font=mono)
        bw = int(bb[2] - bb[0])
        draw.text(
            ((self.page_width - bw) // 2, bot_y),
            bot_str,
            font=mono,
            fill=(155, 155, 155, 255),
        )

    def _select_token_font(
        self,
        tok: _InlineToken,
        font_size: int,
        *,
        heading_level: int,
        is_bold: bool,
        is_italic: bool,
        rng: random.Random,
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        if tok.code or tok.keyword is not None:
            tag_sz = max(
                12,
                round(
                    font_size
                    * (0.62 if self.style == RenderStyle.HANDWRITING else 0.78)
                ),
            )
            return _load_role_font(
                _FontRole.MONO_BOLD if is_bold else _FontRole.MONO_REGULAR,
                tag_sz,
            )

        if self.style == RenderStyle.STYLIZED:
            if heading_level == 1:
                role = (
                    _FontRole.DISPLAY_SERIF_ITALIC
                    if is_italic
                    else _FontRole.DISPLAY_SERIF
                )
                return _load_role_font(role, font_size, custom_font_path=self.font_path)
            if heading_level == 2:
                return _load_role_font(
                    _FontRole.MONO_BOLD,
                    font_size,
                    custom_font_path=self.font_path,
                )
            if is_italic:
                return _load_role_font(
                    _FontRole.DISPLAY_SERIF_ITALIC,
                    round(font_size * 1.12),
                    custom_font_path=self.font_path,
                )
            return _load_role_font(
                _FontRole.SANS_BOLD if is_bold else _FontRole.SANS_REGULAR,
                font_size,
                custom_font_path=self.font_path,
            )

        if self.style == RenderStyle.ARCHITECT:
            if heading_level == 2:
                return _load_role_font(_FontRole.MONO_BOLD, round(font_size * 0.82))
            return _load_role_font(
                _FontRole.ARCHITECT,
                font_size,
                custom_font_path=self.font_path,
            )

        # RenderStyle.HANDWRITING
        if heading_level == 1:
            return _load_role_font(
                _FontRole.ARCHITECT,
                font_size,
                custom_font_path=self.font_path,
            )
        weight = 690 if (is_bold or heading_level > 0) else rng.randint(485, 545)
        return _load_role_font(
            _FontRole.SCRIPT_BOLD if is_bold else _FontRole.SCRIPT_REGULAR,
            font_size,
            custom_font_path=self.font_path,
            weight_override=weight,
        )

    def _split_overlong_token(
        self,
        draw: ImageDraw.ImageDraw,
        tok: _InlineToken,
        *,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        max_width: int,
        pill_pad_x: int,
    ) -> list[_InlineToken]:
        budget = max(24, max_width - pill_pad_x * 2)
        chunks: list[_InlineToken] = []
        rem = tok.text
        while rem:
            bbox_full = draw.textbbox((0, 0), rem, font=font)
            if int(bbox_full[2] - bbox_full[0]) <= budget or len(rem) == 1:
                chunks.append(
                    _InlineToken(
                        text=rem,
                        bold=tok.bold,
                        italic=tok.italic,
                        code=tok.code,
                        strike=tok.strike,
                        highlight=tok.highlight,
                        link_target=tok.link_target,
                        keyword=None,
                    )
                )
                break

            lo = 1
            hi = len(rem) - 1
            best = 1
            while lo <= hi:
                mid = (lo + hi) // 2
                b = draw.textbbox((0, 0), rem[:mid], font=font)
                if int(b[2] - b[0]) <= budget:
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1

            chunks.append(
                _InlineToken(
                    text=rem[:best],
                    bold=tok.bold,
                    italic=tok.italic,
                    code=tok.code,
                    strike=tok.strike,
                    highlight=tok.highlight,
                    link_target=tok.link_target,
                    keyword=None,
                )
            )
            rem = rem[best:]
        return chunks

    def _expand_tokens_for_width(
        self,
        draw: ImageDraw.ImageDraw,
        tokens: list[_InlineToken],
        *,
        max_width: int,
        font_size: int,
        heading_level: int,
        default_bold: bool,
        default_italic: bool,
    ) -> list[_InlineToken]:
        expanded: list[_InlineToken] = []
        measure_rng = random.Random(0)
        for tok in tokens:
            if tok.keyword is not None or len(tok.text) <= 1:
                expanded.append(tok)
                continue
            font = self._select_token_font(
                tok,
                font_size,
                heading_level=heading_level,
                is_bold=default_bold or tok.bold,
                is_italic=default_italic or tok.italic,
                rng=measure_rng,
            )
            pill_pad_x = round(10 * self.scale) if tok.code else 0
            bbox = draw.textbbox((0, 0), tok.text, font=font)
            effective_w = max(4, int(bbox[2] - bbox[0])) + pill_pad_x * 2
            if effective_w <= max_width:
                expanded.append(tok)
            else:
                expanded.extend(
                    self._split_overlong_token(
                        draw,
                        tok,
                        font=font,
                        max_width=max_width,
                        pill_pad_x=pill_pad_x,
                    )
                )
        return expanded

    def _draw_wrapped_tokens(
        self,
        *,
        canvas: Image.Image,
        draw: ImageDraw.ImageDraw,
        tokens: list[_InlineToken],
        x_start: int,
        y_start: int,
        max_width: int,
        font_size: int,
        line_height: int,
        default_bold: bool,
        rng: random.Random,
        keywords_out: list[KeywordSpan],
        links_out: list[LinkSpan],
        heading_level: int = 0,
        default_italic: bool = False,
        ink_shade: int = 0,
    ) -> Rect:
        """Word-wrap and render inline tokens, returning bounding `(left, top, width, height)`."""
        if not tokens:
            return (x_start, y_start, 0, line_height)

        tokens = self._expand_tokens_for_width(
            draw,
            tokens,
            max_width=max_width,
            font_size=font_size,
            heading_level=heading_level,
            default_bold=default_bold,
            default_italic=default_italic,
        )

        space_w = max(
            8,
            round(
                font_size
                * (
                    0.26
                    if self.style == RenderStyle.HANDWRITING
                    else 0.34
                    if heading_level == 2
                    else 0.28
                )
            ),
        )
        cur_x = x_start
        cur_y = y_start
        min_x = x_start
        max_x = x_start
        line_idx = 0

        active_link_target: str | None = None
        active_link_words: list[str] = []
        active_link_rect: list[int] | None = None

        def flush_active_link() -> None:
            nonlocal active_link_target, active_link_words, active_link_rect
            if active_link_target is not None and active_link_rect is not None:
                l_left, l_top, l_right, l_bottom = active_link_rect
                links_out.append(
                    LinkSpan(
                        label=" ".join(active_link_words),
                        target=active_link_target,
                        rect=(
                            max(0, l_left),
                            max(0, l_top),
                            max(4, l_right - l_left),
                            max(4, l_bottom - l_top),
                        ),
                    )
                )
            active_link_target = None
            active_link_words = []
            active_link_rect = None

        for tok in tokens:
            is_bold = default_bold or tok.bold
            is_italic = default_italic or tok.italic
            is_badge = tok.keyword is not None or tok.code
            font = self._select_token_font(
                tok,
                font_size,
                heading_level=heading_level,
                is_bold=is_bold,
                is_italic=is_italic,
                rng=rng,
            )

            render_str = tok.text.upper() if tok.keyword is not None else tok.text
            bbox = draw.textbbox((0, 0), render_str, font=font)
            word_w = max(4, int(bbox[2] - bbox[0]))
            word_h = max(12, int(bbox[3]))
            pill_pad_x = round(10 * self.scale) if is_badge else 0
            effective_w = word_w + pill_pad_x * 2

            if cur_x > x_start and (cur_x + effective_w > x_start + max_width):
                flush_active_link()
                cur_x = x_start
                cur_y += line_height
                line_idx += 1

            # Optional ==highlight== chisel-marker swipe behind token
            if tok.highlight:
                _draw_highlighter_swipe(
                    canvas,
                    cur_x,
                    cur_y,
                    effective_w,
                    font_size,
                    hand_drawn=self._is_hand_drawn,
                    rng=rng,
                    shade=220,
                )

            if is_badge:
                # Minimalist stationery tag pill / inline code chip
                badge_top = cur_y + round((font_size - word_h) * 0.32)
                badge_h = max(
                    round(font_size * 0.72),
                    int(bbox[3] - bbox[1]) + round(10 * self.scale),
                )
                pill_rect = (
                    cur_x,
                    badge_top,
                    cur_x + effective_w,
                    badge_top + badge_h,
                )
                draw.rounded_rectangle(
                    pill_rect,
                    radius=round(8 * self.scale),
                    fill=(238, 238, 238, 255),
                    outline=(185, 185, 185, 255) if tok.keyword else None,
                    width=1,
                )
                ty = badge_top + (badge_h - int(bbox[3] - bbox[1])) // 2 - int(bbox[1])
                draw.text(
                    (cur_x + pill_pad_x, ty),
                    render_str,
                    font=font,
                    fill=(45, 45, 45, 255),
                )
                word_rect = (cur_x, badge_top, effective_w, badge_h)
                advance = effective_w + space_w
            elif self._is_hand_drawn:
                wave_amp = 1.6 if self.style == RenderStyle.HANDWRITING else 0.7
                baseline_wave = (
                    math.sin(line_idx * 0.85 + (cur_x - x_start) * 0.005)
                    * wave_amp
                    * self.scale
                )
                jitter_y = round(
                    baseline_wave
                    + rng.uniform(
                        -wave_amp * 0.6 * self.scale, wave_amp * 0.6 * self.scale
                    )
                )
                rot_amp = 1.1 if self.style == RenderStyle.HANDWRITING else 0.45
                patch, raw_w, raw_h = _render_pen_word(
                    render_str,
                    font,
                    rng,
                    ink_shade=ink_shade,
                    angle_deg=0.3 if heading_level > 0 else rot_amp,
                )
                paste_x = max(0, cur_x - 10)
                paste_y = max(0, cur_y + jitter_y - 8)
                canvas.alpha_composite(patch, dest=(paste_x, paste_y))
                word_rect = (cur_x, cur_y + jitter_y, raw_w, raw_h)
                advance = (
                    raw_w
                    + space_w
                    + round(rng.uniform(-1.0 * self.scale, 2.5 * self.scale))
                )
            else:
                y_off = (
                    -round(font_size * 0.08)
                    if (is_italic and not default_italic)
                    else 0
                )
                draw.text(
                    (cur_x, cur_y + y_off),
                    render_str,
                    font=font,
                    fill=(ink_shade, ink_shade, ink_shade, 255),
                )
                word_rect = (cur_x, cur_y, word_w, word_h)
                advance = word_w + space_w

            if tok.strike:
                strike_y = word_rect[1] + round(word_rect[3] * 0.56)
                if self._is_hand_drawn:
                    _draw_hand_line(
                        draw,
                        word_rect[0] - 2,
                        strike_y,
                        word_rect[0] + word_rect[2] + 2,
                        strike_y,
                        rng,
                        fill=(30, 30, 30, 255),
                        width=max(2, round(2.2 * self.scale)),
                    )
                else:
                    draw.line(
                        [
                            (word_rect[0], strike_y),
                            (word_rect[0] + word_rect[2], strike_y),
                        ],
                        fill=(60, 60, 60, 255),
                        width=max(2, round(2 * self.scale)),
                    )

            if tok.link_target is not None:
                ul_y = word_rect[1] + round(word_rect[3] * 0.94)
                draw.line(
                    [(word_rect[0], ul_y), (word_rect[0] + word_rect[2], ul_y)],
                    fill=(95, 95, 95, 255),
                    width=max(1, round(1.6 * self.scale)),
                )
                if (
                    active_link_target == tok.link_target
                    and active_link_rect is not None
                ):
                    active_link_words.append(tok.text)
                    active_link_rect[2] = word_rect[0] + word_rect[2]
                    active_link_rect[3] = max(
                        active_link_rect[3], word_rect[1] + word_rect[3]
                    )
                else:
                    flush_active_link()
                    active_link_target = tok.link_target
                    active_link_words = [tok.text]
                    active_link_rect = [
                        word_rect[0],
                        word_rect[1],
                        word_rect[0] + word_rect[2],
                        word_rect[1] + word_rect[3],
                    ]
            else:
                flush_active_link()

            if tok.keyword is not None:
                keywords_out.append(
                    KeywordSpan(
                        keyword=tok.keyword,
                        rect=(
                            max(0, word_rect[0]),
                            max(0, word_rect[1]),
                            max(4, word_rect[2]),
                            max(4, word_rect[3]),
                        ),
                    )
                )

            max_x = max(max_x, word_rect[0] + word_rect[2])
            cur_x += max(6, advance)

        flush_active_link()
        total_h = (cur_y - y_start) + line_height
        return (min_x, y_start, max(4, max_x - min_x), total_h)


def render_markdown(
    markdown: str,
    *,
    style: RenderStyle | str = RenderStyle.STYLIZED,
    background: BackgroundStyle | str = BackgroundStyle.WHITE,
    page_width: int = fileformat.PAGE_WIDTH,
    page_height: int = fileformat.PAGE_HEIGHT,
    font_path: str | os.PathLike[str] | None = None,
    font_size: int | None = None,
    seed: int = 0,
    extract_keywords: bool = True,
) -> list[RenderedPage]:
    """Paginate and render Markdown into transparent foreground `RenderedPage` objects.

    Unlike `create_notebook()`, `render_markdown()` performs pure visual layout without
    packing a `.note` binary. Note that `RenderedPage.image` contains only the transparent
    RGBA foreground layer; pair with `render_background(background, page_width, page_height)`
    if you want a flattened RGB preview outside of `NotebookAuthor`.
    """
    renderer = MarkdownRenderer(
        style=style,
        background=background,
        page_width=page_width,
        page_height=page_height,
        font_path=font_path,
        font_size=font_size,
        seed=seed,
        extract_keywords=extract_keywords,
    )
    return renderer.render(markdown)


def _paginate_overlay_inner(
    markdown: str,
    *,
    style: RenderStyle | str,
    card_width: int,
    max_card_h: int,
    scale: float,
    card_pad_x: int,
    card_pad_y: int,
    font_path: str | os.PathLike[str] | None,
    font_size: int | None,
    seed: int,
) -> list[RenderedPage]:
    inner_renderer = MarkdownRenderer(
        style=style,
        background=BackgroundStyle.WHITE,
        page_width=card_width,
        page_height=max_card_h,
        font_path=font_path,
        font_size=font_size,
        seed=seed,
        extract_keywords=False,
        show_page_furniture=False,
    )
    inner_renderer.paper_margin_x = card_pad_x
    inner_renderer.gutter_w = round(28 * scale)
    inner_renderer.margin_x = card_pad_x + inner_renderer.gutter_w
    inner_renderer.right_margin_x = card_pad_x
    inner_renderer.margin_top = card_pad_y + round(36 * scale)
    inner_renderer.margin_bottom = card_pad_y
    return inner_renderer.render(markdown)


def render_overlay_cards(
    markdown: str,
    *,
    style: RenderStyle | str = RenderStyle.STYLIZED,
    page_width: int = fileformat.PAGE_WIDTH,
    page_height: int = fileformat.PAGE_HEIGHT,
    font_path: str | os.PathLike[str] | None = None,
    font_size: int | None = None,
    seed: int = 0,
) -> list[RenderedPage]:
    """Render Markdown into bottom-anchored opaque-white (`color.WHITE`) stationery cards.

    Designed for secondary toggleable Supernote layers (`LAYER1`–`LAYER3`), such as
    flashcard answer keys, review hints, or non-destructive AI coaching notes:

    - Pixels outside the card remain RGBA `(255, 255, 255, 0)` -> `color.TRANSPARENT`
      (`0xFF`), allowing the main page content above the card to show through.
    - The card interior is filled with `color.WHITE` (`0xFE`) plus a crisp border,
      drop shadow, and `LAYER · OVERLAY` index tab so background dots/lines beneath the
      card are cleanly masked when the layer is toggled visible.
    """
    scale = page_width / fileformat.PAGE_WIDTH
    card_margin_x = round(92 * scale)
    card_pad_x = round(38 * scale)
    card_pad_y = round(30 * scale)
    card_width = page_width - 2 * card_margin_x
    max_card_h = round(page_height * 0.40)

    inner_pages = _paginate_overlay_inner(
        markdown,
        style=style,
        card_width=card_width,
        max_card_h=max_card_h,
        scale=scale,
        card_pad_x=card_pad_x,
        card_pad_y=card_pad_y,
        font_path=font_path,
        font_size=font_size,
        seed=seed,
    )
    if len(inner_pages) > 1:
        max_card_h = round(page_height * 0.78)
        inner_pages = _paginate_overlay_inner(
            markdown,
            style=style,
            card_width=card_width,
            max_card_h=max_card_h,
            scale=scale,
            card_pad_x=card_pad_x,
            card_pad_y=card_pad_y,
            font_path=font_path,
            font_size=font_size,
            seed=seed,
        )

    mono_tab = _load_role_font(_FontRole.MONO_BOLD, round(17 * scale))
    result: list[RenderedPage] = []
    for ipage in inner_pages:
        alpha_bbox = ipage.image.getbbox()
        content_bottom = (
            min(max_card_h, int(alpha_bbox[3]) + card_pad_y)
            if alpha_bbox is not None
            else round(180 * scale)
        )
        card_h = max(round(170 * scale), content_bottom)
        card_top = page_height - round(112 * scale) - card_h

        full = Image.new("RGBA", (page_width, page_height), (255, 255, 255, 0))
        fdraw = ImageDraw.Draw(full)
        shadow_off = round(7 * scale)
        fdraw.rectangle(
            (
                card_margin_x + shadow_off,
                card_top + shadow_off,
                card_margin_x + card_width + shadow_off,
                card_top + card_h + shadow_off,
            ),
            fill=(color.GRAY, color.GRAY, color.GRAY, 255),
        )
        fdraw.rectangle(
            (
                card_margin_x,
                card_top,
                card_margin_x + card_width,
                card_top + card_h,
            ),
            fill=(color.WHITE, color.WHITE, color.WHITE, 255),
            outline=(20, 20, 20, 255),
            width=max(2, round(2.5 * scale)),
        )
        # Inverted black index tab in top-left corner of the card ("LAYER 01 · NOTES")
        tab_label = " LAYER · OVERLAY "
        tb = fdraw.textbbox((0, 0), tab_label, font=mono_tab)
        tw = int(tb[2] - tb[0]) + round(16 * scale)
        th = round(28 * scale)
        fdraw.rectangle(
            (card_margin_x, card_top, card_margin_x + tw, card_top + th),
            fill=(20, 20, 20, 255),
        )
        fdraw.text(
            (card_margin_x + round(8 * scale), card_top + round(4 * scale)),
            tab_label,
            font=mono_tab,
            fill=(color.WHITE, color.WHITE, color.WHITE, 255),
        )

        cropped = ipage.image.crop((0, 0, card_width, card_h))
        full.alpha_composite(cropped, dest=(card_margin_x, card_top))
        result.append(
            RenderedPage(
                image=full,
                text=ipage.text,
                headings=ipage.headings,
                keywords=ipage.keywords,
                links=ipage.links,
            )
        )
    return result
