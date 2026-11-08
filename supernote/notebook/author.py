"""Declarative builder API for authoring and extending Supernote `.note` notebooks.

How Programmatic `.note` Authoring Works
----------------------------------------
A Supernote X2 `.note` file (`SN_FILE_VER_20230015` / `SN_FILE_VER_20260016`) is a
block-addressed binary archive terminated by a footer metadata block (`<KEY:OFFSET>`).
Each page owns up to five ordered raster layers (`BGLAYER`, `MAINLAYER`, `LAYER1`,
`LAYER2`, `LAYER3`), a `#`-escaped JSON `LAYERINFO` visibility table, a unique
timestamped `PAGEID`, and optional document-level navigation blocks (`Title` TOC
entries, searchable `Keyword` tags, and internal/external `Link` anchors).

`NotebookAuthor` composes three orthogonal subsystems into a clean builder API:

1. **Rendering (`supernote.notebook.renderer`)**: Paginates Markdown & Bullet Journal
   Rapid-Logging shorthand into transparent foreground bitmaps plus intrinsic bounding
   spans (`HeadingSpan`, `KeywordSpan`, `LinkSpan`).
2. **Layer Compression (`supernote.notebook.encoder`)**: Encodes foreground and overlay
   layers into X2 240-shade anti-aliased `RATTA_RLE` streams and custom background
   templates into MD5-indexed `PNG` blocks.
3. **Binary Reconstruction (`supernote.notebook.manipulator.reconstruct`)**: Relocates
   block addresses, preserves any pre-existing on-device `TOTALPATH` strokes or
   `RECOGNTEXT` real-time recognition payloads on untouched pages, and emits a valid
   `.note` byte stream ready for Supernote devices, Cloud sync, or `ImageConverter`.

Cooperative Human + Agent Layer Philosophy
------------------------------------------
Physical Supernote stylus strokes live on `MAINLAYER`. When an AI agent, CLI script, or
sync service co-authors a notebook alongside a human writer, choosing the right layer
prevents destructive collisions:

- **Stationery Templates on `BGLAYER` (`style="stylized"` default)**:
  Editorial planners, agendas, and habit trackers are composited onto `BGLAYER` as a
  custom `user_stylized` PNG template while `MAINLAYER` stays completely blank. On the
  device, the human can handwrite, erase, and lasso-move strokes freely on `MAINLAYER`
  without ever erasing the generated layout underneath.
- **Simulated Ink on `MAINLAYER` (`style="handwriting"` / `"architect"` default)**:
  Places anti-aliased `RATTA_RLE` ink onto `MAINLAYER` over native `style_*` paper
  (`dots`, `ruled`, `grid`), producing realistic handwritten pages for OCR/VLM E2E
  testing or standalone notes.
- **Non-Destructive Overlays on `LAYER1`–`LAYER3` (`hidden_layer_markdown`)**:
  Places flashcard solutions, margin coaching cards, or review annotations onto a
  secondary layer (`isVisible: False` by default) that users can toggle on/off via the
  Supernote layer menu or inspect programmatically via `VisibilityOverlay`.

Example
-------
```python
from supernote.notebook import NotebookAuthor

author = NotebookAuthor(equipment="N6", seed=42)
author.add_markdown(
    "#### NOV 2026 · DAILY LOG\\n# Focus\\n\\n* - [ ] Ship ==notebook API== #roadmap",
    style="stylized",
    background="dots",
    hidden_layer_markdown="### Coach\\n! - [-] Block 90m before noon for deep work.",
    auto_toc=True,
)
author.save("daily_focus.note")
```
"""

from __future__ import annotations

import base64
import copy
import io
import json
import os
import random
import re
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from PIL import Image

from . import color, exceptions, fileformat, schema
from .decoder import RattaRleDecoder
from .encoder import PngEncoder, RattaRleX2Encoder
from .manipulator import SUPPORTED_RECONSTRUCT_SIGNATURES, reconstruct
from .parser import load
from .renderer import (
    BackgroundStyle,
    HeadingSpan,
    KeywordSpan,
    LinkSpan,
    MarkdownRenderer,
    Rect,
    RenderedPage,
    RenderStyle,
    get_pagestyle_name,
    render_background,
    render_overlay_cards,
)

DEFAULT_SIGNATURE = "SN_FILE_VER_20230015"
VALID_EQUIPMENT = ("N6", "N5", "A5X", "A6X", "A6X2")
VALID_USER_LAYERS = ("MAINLAYER", "LAYER1", "LAYER2", "LAYER3")
ALL_LAYERS = ("BGLAYER", "MAINLAYER", "LAYER1", "LAYER2", "LAYER3")

_ALPHANUM = string.ascii_letters + string.digits
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SPECIAL_WHITE_STYLE_BLOCK_SIZE = 0x140E


def generate_supernote_id(
    prefix: str,
    timestamp: datetime | None = None,
    *,
    rng: random.Random | None = None,
) -> str:
    """Generate a Supernote FILE_ID ('F...') or PAGEID ('P...') identifier.

    Format matches device firmware (`{P|F}{YYYYMMDDHHMMSSffffff}{12-char-alnum}`),
    which satisfies both `is_valid_page_id()` and `infer_page_date()`.
    """
    if prefix not in ("F", "P"):
        raise ValueError(f"prefix must be 'F' or 'P', got {prefix!r}")
    dt = timestamp if timestamp is not None else datetime.now(tz=UTC)
    rand_src = rng if rng is not None else random
    suffix = "".join(rand_src.choice(_ALPHANUM) for _ in range(12))
    return f"{prefix}{dt.strftime('%Y%m%d%H%M%S%f')}{suffix}"


@dataclass(frozen=True)
class ExtraLayerSpec:
    """Configuration for an additional foreground or overlay layer (`LAYER1`–`LAYER3`)."""

    image: Image.Image
    """PIL image to encode onto the layer via `RattaRleX2Encoder`."""

    visible: bool = True
    """Initial layer visibility recorded in the page's `LAYERINFO` table."""

    white_is_transparent: bool = True
    """Map white pixels to `color.TRANSPARENT` (`False` keeps opaque white overlay cards)."""


@dataclass(frozen=True)
class AuthoredPageInfo:
    """Metadata and ground-truth content for a page added via `NotebookAuthor`."""

    page_index: int
    """0-based index of the page within the authored `Notebook`."""

    page_id: str
    """Assigned Supernote `<PAGEID>` (`P...`)."""

    text: str = ""
    """Plain-text transcript emitted for the page."""

    headings: tuple[HeadingSpan, ...] = ()
    """Rendered heading bounding spans on the page."""

    keywords: tuple[KeywordSpan, ...] = ()
    """Rendered `#hashtag` keyword bounding spans on the page."""

    links: tuple[LinkSpan, ...] = ()
    """Rendered web and internal page-jump link bounding spans on the page."""


def _encode_layer_info_metadata(
    *,
    active_layers: set[str],
    visibility: Mapping[str, bool],
) -> str:
    """Build `#`-escaped LAYERINFO JSON matching Supernote firmware conventions."""
    layer_defs = [
        (3, "LAYER3", "Layer 3", False),
        (2, "LAYER2", "Layer 2", False),
        (1, "LAYER1", "Layer 1", False),
        (0, "MAINLAYER", "Main Layer", False),
        (-1, "BGLAYER", "Background Layer", True),
    ]
    entries = []
    for layer_id, key, label, is_bg in layer_defs:
        is_present = key in active_layers or key in ("MAINLAYER", "BGLAYER")
        entries.append(
            {
                "layerId": layer_id,
                "name": label,
                "isBackgroundLayer": is_bg,
                "isAllowAdd": is_bg,
                "isCurrentLayer": key == "MAINLAYER",
                "isVisible": bool(visibility.get(key, True)),
                "isDeleted": not is_present,
                "isAllowUp": False,
                "isAllowDown": False,
            }
        )
    raw_json = json.dumps(entries, separators=(",", ":"))
    return raw_json.replace(":", "#")


def _composite_on_paper(
    paper_l: Image.Image,
    foreground_rgba: Image.Image,
) -> Image.Image:
    """Composite a transparent RGBA foreground onto a Supernote L-mode paper template."""
    # Convert Supernote L-mode template (where 0xFF is white paper) to opaque RGBA white canvas
    base = Image.new("RGBA", paper_l.size, (255, 255, 255, 255))
    rgb_paper = paper_l.convert("RGBA")
    base.alpha_composite(rgb_paper)
    fg = (
        foreground_rgba.convert("RGBA")
        if foreground_rgba.mode != "RGBA"
        else foreground_rgba
    )
    if fg.size != base.size:
        resized = Image.new("RGBA", base.size, (255, 255, 255, 0))
        resized.paste(fg, (0, 0))
        fg = resized
    base.alpha_composite(fg)
    return base.convert("RGB")


@dataclass
class _PendingPageLink:
    source_page_index: int
    target_page_index: int
    rect: Rect
    raw_target: str = ""


def _transcode_legacy_rle_to_x2(notebook: fileformat.Notebook) -> None:
    """Transcode X1 RATTA_RLE layer, title, and link bitmaps to X2 color codes."""
    legacy_decoder = RattaRleDecoder()
    x2_encoder = RattaRleX2Encoder(highres_grayscale=True)
    base_w = notebook.width
    base_h = notebook.height

    for page in notebook.pages:
        horizontal = page.is_horizontal()
        page_style = page.style
        for layer in page.layers:
            layer_name = layer.name
            binary = layer.content
            if layer_name is None or binary is None:
                continue
            if layer.bitmap_protocol != schema.LayerProtocol.RATTA_RLE:
                continue
            all_blank = (
                layer_name == "BGLAYER"
                and page_style == "style_white"
                and len(binary) == _SPECIAL_WHITE_STYLE_BLOCK_SIZE
            )
            raw_bytes, size, _ = legacy_decoder.decode(
                binary,
                base_w,
                base_h,
                palette=color.DEFAULT_COLORPALETTE,
                all_blank=all_blank,
                horizontal=horizontal,
            )
            layer.content = x2_encoder.encode(Image.frombytes("L", size, raw_bytes))

    for title in notebook.titles:
        content = title.content
        if content is not None and title.protocol == "RATTA_RLE":
            p_idx = title.page_number
            horiz = (
                notebook.pages[p_idx].is_horizontal()
                if 0 <= p_idx < len(notebook.pages)
                else False
            )
            raw_bytes, size, _ = legacy_decoder.decode(
                content,
                base_w,
                base_h,
                palette=color.DEFAULT_COLORPALETTE,
                horizontal=horiz,
            )
            title.content = x2_encoder.encode(Image.frombytes("L", size, raw_bytes))

    for link in notebook.links:
        content = link.content
        if content is not None and link.metadata.protocol == "RATTA_RLE":
            p_idx = link.page_number
            horiz = (
                notebook.pages[p_idx].is_horizontal()
                if 0 <= p_idx < len(notebook.pages)
                else False
            )
            raw_bytes, size, _ = legacy_decoder.decode(
                content,
                base_w,
                base_h,
                palette=color.DEFAULT_COLORPALETTE,
                horizontal=horiz,
            )
            link.content = x2_encoder.encode(Image.frombytes("L", size, raw_bytes))


class NotebookAuthor:
    """Stateful builder for creating new `.note` notebooks or appending to existing ones.

    Supports both Nomad (`equipment="N6"`, `1404x1872`) and Manta / A5X2
    (`equipment="N5"`, `1920x2560`) page profiles, forward/backward internal page links
    (`[Jump](page:2)` or `[Next](page:+1)` resolved lazily during `to_bytes()`), TOC
    `Title` bitmaps, and non-destructive appending onto existing notebooks via
    `NotebookAuthor.from_notebook()`.
    """

    def __init__(
        self,
        *,
        equipment: str = "N6",
        signature: str = DEFAULT_SIGNATURE,
        file_id: str | None = None,
        created_at: datetime | None = None,
        seed: int = 0,
    ) -> None:
        """Initialize a new empty X2-compatible `NotebookAuthor`.

        Args:
            equipment: Device profile (`"N6"` for `1404x1872` Nomad, `"N5"` for `1920x2560` Manta).
            signature: Format version (`"SN_FILE_VER_20230015"` or `"SN_FILE_VER_20260016"`).
            file_id: Optional explicit `FILE_ID` (`F...`); auto-generated when omitted.
            created_at: Base UTC timestamp used to mint sequential `FILE_ID` and `PAGEID` values.
            seed: Deterministic RNG seed for ID suffixes and simulated handwriting.
        """
        if equipment not in VALID_EQUIPMENT:
            raise ValueError(
                f"equipment must be one of {VALID_EQUIPMENT}, got {equipment!r}"
            )
        if signature not in SUPPORTED_RECONSTRUCT_SIGNATURES:
            raise ValueError(
                f"signature must be one of {sorted(SUPPORTED_RECONSTRUCT_SIGNATURES)}, got {signature!r}"
            )
        if file_id is not None and not _SAFE_ID_RE.fullmatch(file_id):
            raise ValueError(
                f"file_id must match {_SAFE_ID_RE.pattern!r}, got {file_id!r}"
            )
        self._rng = random.Random(seed)
        self._created_at = (
            created_at if created_at is not None else datetime.now(tz=UTC)
        )
        self._page_counter = 0
        self._png_encoder = PngEncoder()
        self._pending_page_links: list[_PendingPageLink] = []

        resolved_file_id = file_id or generate_supernote_id(
            "F", self._created_at, rng=self._rng
        )
        header: dict[str, Any] = {
            "MODULE_LABEL": "SNFILE_FEATURE",
            "FILE_TYPE": "NOTE",
            "APPLY_EQUIPMENT": equipment,
            "FINALOPERATION_PAGE": "1",
            "FINALOPERATION_LAYER": "1",
            "DEVICE_DPI": "0",
            "SOFT_DPI": "0",
            "FILE_PARSE_TYPE": "0",
            "RATTA_ETMD": "0",
            "APP_VERSION": "0",
            "FILE_ID": resolved_file_id,
            "FILE_RECOGN_TYPE": "0",
            "FILE_RECOGN_LANGUAGE": "none",
            "HORIZONTAL_CHECK": "0",
            "IS_OLD_APPLY_EQUIPMENT": "1",
            "ANTIALIASING_CONVERT": "2",
        }
        footer: dict[str, Any] = {"FILE_FEATURE": "24", "DIRTY": "0"}
        metadata = schema.SupernoteMetadata(
            type="note",
            signature=signature,
            header=header,
            footer=footer,
            pages=[],
        )
        self._notebook = fileformat.Notebook(metadata)
        self._rle_encoder = RattaRleX2Encoder(
            highres_grayscale=self._notebook.supports_highres_grayscale()
        )
        self._blank_rle_cache: dict[tuple[int, int], bytes] = {}
        self._paper_rle_cache: dict[tuple[str, int, int], bytes] = {}

    @classmethod
    def from_notebook(
        cls,
        notebook: fileformat.Notebook,
        *,
        seed: int = 0,
        upgrade_signature: bool = True,
    ) -> NotebookAuthor:
        """Create a `NotebookAuthor` wrapping a deep copy of an existing `Notebook`.

        Existing pages keep their original `PAGEID`, `TOTALPATH` vector strokes,
        `RECOGNTEXT` / `RECOGNFILE` recognition payloads, titles, keywords, and links
        intact so new pages or annotations can be appended non-destructively.

        Args:
            notebook: Parsed `Notebook` instance (e.g. from `load_notebook()`).
            seed: Deterministic RNG seed for newly appended pages.
            upgrade_signature: When `True`, upgrades older pre-X2 format signatures to
                `SN_FILE_VER_20230015` and transcodes legacy `RATTA_RLE` color codes
                so `reconstruct()` preserves exact grayscale luminance.
        """
        if notebook.loaded_page_number is not None:
            raise ValueError(
                "Cannot create NotebookAuthor from a partially loaded Notebook (loaded_page_number is set); load the full notebook first"
            )
        for idx, page in enumerate(notebook.pages):
            if not page.is_layer_supported():
                raise ValueError(
                    f"Page {idx} uses a legacy non-layered format unsupported for reconstruction"
                )

        cloned = copy.deepcopy(notebook)
        meta = cloned.metadata
        original_highres = cloned.supports_highres_grayscale()
        if meta.signature not in SUPPORTED_RECONSTRUCT_SIGNATURES:
            if not upgrade_signature:
                raise ValueError(
                    f"Notebook signature {meta.signature!r} is not supported for reconstruction"
                )
            if not original_highres:
                _transcode_legacy_rle_to_x2(cloned)
            meta.signature = DEFAULT_SIGNATURE
            cloned.signature = DEFAULT_SIGNATURE

        equipment = str(meta.header.apply_equipment or "N6")
        file_id = cloned.file_id
        author = cls(
            equipment=equipment,
            signature=meta.signature,
            file_id=file_id,
            seed=seed,
        )
        if not cloned.file_id:
            meta.header.file_id = author.file_id
        author._notebook = cloned
        author._page_counter = cloned.total_pages
        return author

    @property
    def page_width(self) -> int:
        return self._notebook.width

    @property
    def page_height(self) -> int:
        return self._notebook.height

    @property
    def equipment(self) -> str:
        return str(self._notebook.metadata.header.apply_equipment or "N6")

    @property
    def file_id(self) -> str:
        fid = self._notebook.file_id
        if not fid:
            raise exceptions.ManipulatorException("Notebook header is missing FILE_ID")
        return fid

    def _get_blank_rle(self, width: int, height: int) -> bytes:
        key = (width, height)
        if key not in self._blank_rle_cache:
            blank = Image.new("L", (width, height), color=color.TRANSPARENT)
            self._blank_rle_cache[key] = self._rle_encoder.encode(blank)
        return self._blank_rle_cache[key]

    def _get_paper_rle(
        self, background: BackgroundStyle, width: int, height: int
    ) -> bytes:
        key = (background.value, width, height)
        if key not in self._paper_rle_cache:
            img = render_background(background, width, height)
            self._paper_rle_cache[key] = self._rle_encoder.encode(img)
        return self._paper_rle_cache[key]

    def _next_page_id(self, created_at: datetime | None = None) -> str:
        ts = (
            created_at
            if created_at is not None
            else (self._created_at + timedelta(seconds=self._page_counter))
        )
        self._page_counter += 1
        return generate_supernote_id("P", ts, rng=self._rng)

    def add_page(
        self,
        *,
        background: BackgroundStyle | str = BackgroundStyle.WHITE,
        custom_background: Image.Image | None = None,
        custom_style_name: str = "stylized",
        main_image: Image.Image | None = None,
        main_visible: bool = True,
        main_white_is_transparent: bool = True,
        extra_layers: Mapping[str, ExtraLayerSpec | Image.Image] | None = None,
        background_visible: bool = True,
        page_id: str | None = None,
        created_at: datetime | None = None,
        horizontal: bool = False,
    ) -> str:
        """Append a single page from raw layer images or built-in paper styles.

        Use `add_page()` when supplying custom PIL `Image` layers directly (such as
        diagrams, custom stationery PNGs, or multi-layer visual fixtures). For Markdown
        and Bullet Journal text layout, prefer `add_markdown()`.

        Args:
            background: Built-in paper style (`"white"`, `"dots"`, `"ruled"`, `"grid"`),
                used when `custom_background` is `None`.
            custom_background: Optional PIL image encoded as a `user_<custom_style_name>`
                PNG on `BGLAYER` (portrait pages only).
            custom_style_name: Suffix for `PAGESTYLE = "user_<name>"` when `custom_background` is set.
            main_image: Optional PIL image encoded via `RATTA_RLE` onto `MAINLAYER`.
            main_visible: Initial visibility flag for `MAINLAYER` in `LAYERINFO`.
            main_white_is_transparent: Map white pixels on `main_image` to transparent (`0x62`).
            extra_layers: Optional mapping of `"LAYER1"`, `"LAYER2"`, or `"LAYER3"` to an
                `ExtraLayerSpec` or PIL `Image`.
            background_visible: Initial visibility flag for `BGLAYER` in `LAYERINFO`.
            page_id: Optional explicit `PAGEID` (`P...`); auto-generated when omitted.
            created_at: Optional UTC timestamp encoded into the generated `PAGEID`.
            horizontal: When `True`, creates a landscape-oriented page (`(height, width)`).

        Returns:
            The assigned `PAGEID` string for the newly appended page.
        """
        if horizontal and custom_background is not None:
            raise ValueError(
                "custom PNG backgrounds are only supported on portrait pages; use RATTA_RLE layers for horizontal pages"
            )
        if page_id is not None:
            if not _SAFE_ID_RE.fullmatch(page_id):
                raise ValueError(
                    f"page_id must match {_SAFE_ID_RE.pattern!r}, got {page_id!r}"
                )
            if any(p.page_id == page_id for p in self._notebook.pages):
                raise ValueError(f"Duplicate page_id {page_id!r} in notebook")

        w, h = (
            (self.page_height, self.page_width)
            if horizontal
            else (self.page_width, self.page_height)
        )
        resolved_page_id = page_id or self._next_page_id(created_at)

        if custom_background is not None:
            png_bytes, md5_hex = self._png_encoder.encode_with_md5(
                custom_background, w, h
            )
            safe_name = "".join(
                ch if ch.isalnum() or ch == "_" else "_" for ch in custom_style_name
            )
            pagestyle = f"user_{safe_name or 'custom'}"
            pagestyle_md5 = md5_hex
            bg_bytes = png_bytes
        else:
            bg_enum = BackgroundStyle(background)
            pagestyle = get_pagestyle_name(
                bg_enum, equipment=self.equipment, horizontal=horizontal
            )
            pagestyle_md5 = "0"
            bg_bytes = self._get_paper_rle(bg_enum, w, h)

        if main_image is not None:
            resized_main = (
                main_image
                if main_image.size == (w, h)
                else self._fit_layer_image(main_image, w, h)
            )
            main_bytes = self._rle_encoder.encode(
                resized_main, white_is_transparent=main_white_is_transparent
            )
        else:
            main_bytes = self._get_blank_rle(w, h)

        active_layers: set[str] = {"MAINLAYER", "BGLAYER"}
        visibility: dict[str, bool] = {
            "BGLAYER": background_visible,
            "MAINLAYER": main_visible,
            "LAYER1": True,
            "LAYER2": True,
            "LAYER3": True,
        }
        extra_encoded: dict[str, bytes] = {}
        if extra_layers:
            for layer_key, spec_or_img in extra_layers.items():
                if layer_key not in ("LAYER1", "LAYER2", "LAYER3"):
                    raise ValueError(
                        f"extra_layers keys must be LAYER1, LAYER2, or LAYER3; got {layer_key!r}"
                    )
                spec = (
                    spec_or_img
                    if isinstance(spec_or_img, ExtraLayerSpec)
                    else ExtraLayerSpec(image=spec_or_img)
                )
                fitted = (
                    spec.image
                    if spec.image.size == (w, h)
                    else self._fit_layer_image(spec.image, w, h)
                )
                extra_encoded[layer_key] = self._rle_encoder.encode(
                    fitted, white_is_transparent=spec.white_is_transparent
                )
                active_layers.add(layer_key)
                visibility[layer_key] = spec.visible

        layer_order_top_down = [
            k
            for k in ("LAYER3", "LAYER2", "LAYER1", "MAINLAYER", "BGLAYER")
            if k in active_layers
        ]
        layer_info_str = _encode_layer_info_metadata(
            active_layers=active_layers, visibility=visibility
        )

        layers_meta: list[dict[str, Any]] = []
        layer_contents: list[bytes | None] = []
        for key in ("MAINLAYER", "LAYER1", "LAYER2", "LAYER3", "BGLAYER"):
            if key == "MAINLAYER":
                layers_meta.append(self._make_layer_meta("MAINLAYER"))
                layer_contents.append(main_bytes)
            elif key == "BGLAYER":
                bg_protocol = (
                    schema.LayerProtocol.PNG
                    if custom_background is not None
                    else schema.LayerProtocol.RATTA_RLE
                )
                layers_meta.append(
                    self._make_layer_meta("BGLAYER", protocol=bg_protocol)
                )
                layer_contents.append(bg_bytes)
            elif key in extra_encoded:
                layers_meta.append(self._make_layer_meta(key))
                layer_contents.append(extra_encoded[key])
            else:
                layers_meta.append({})
                layer_contents.append(None)

        orientation = (
            fileformat.Page.ORIENTATION_HORIZONTAL
            if horizontal
            else fileformat.Page.ORIENTATION_VERTICAL
        )
        page_info: dict[str, Any] = {
            "PAGESTYLE": pagestyle,
            "PAGESTYLEMD5": pagestyle_md5,
            "LAYERINFO": layer_info_str,
            "LAYERSEQ": ",".join(layer_order_top_down),
            "MAINLAYER": "0",
            "LAYER1": "0",
            "LAYER2": "0",
            "LAYER3": "0",
            "BGLAYER": "0",
            "TOTALPATH": "0",
            "THUMBNAILTYPE": "0",
            "RECOGNSTATUS": "0",
            "RECOGNTEXT": "0",
            "RECOGNFILE": "0",
            "PAGEID": resolved_page_id,
            "RECOGNTYPE": "0",
            "RECOGNFILESTATUS": "0",
            "RECOGNLANGUAGE": "none",
            "EXTERNALLINKINFO": "0",
            "IDTABLE": "0",
            "ORIENTATION": orientation,
            "PAGETEXTBOX": "0",
            "DISABLE": "none",
            schema.KEY_LAYERS: layers_meta,
        }

        page = fileformat.Page(
            page_info,
            page_number=len(self._notebook.pages),
            notebook=self._notebook,
        )
        for idx, content_bytes in enumerate(layer_contents):
            if content_bytes is not None:
                page.layer(idx).content = content_bytes

        self._notebook.pages.append(page)
        self._notebook.metadata.pages.append(page.metadata)
        self._notebook.metadata.header.final_operation_page = len(self._notebook.pages)
        return resolved_page_id

    def add_markdown(
        self,
        markdown: str,
        *,
        style: RenderStyle | str = RenderStyle.STYLIZED,
        background: BackgroundStyle | str = BackgroundStyle.WHITE,
        layer: str | None = None,
        layer_visible: bool = True,
        hidden_layer_markdown: str | None = None,
        hidden_layer_name: str = "LAYER1",
        auto_toc: bool = False,
        extract_keywords: bool = True,
        attach_links: bool = True,
        page_dates: Sequence[datetime] | None = None,
        default_page_date: datetime | None = None,
        font_path: str | os.PathLike[str] | None = None,
        font_size: int | None = None,
        seed: int | None = None,
    ) -> list[AuthoredPageInfo]:
        """Render Markdown into one or more notebook pages and append them.

        Default Layer Routing:
        - `style="stylized"` composites rendered content + paper onto `BGLAYER` as a
          custom `user_stylized` PNG template (leaving `MAINLAYER` empty so physical
          Supernote handwriting never overwrites or erases the template).
        - `style="handwriting"` and `style="architect"` encode simulated ink onto
          `MAINLAYER` (`RATTA_RLE`) over the chosen native `BGLAYER` paper template.
        - Passing `layer="BGLAYER" | "MAINLAYER" | "LAYER1" | "LAYER2" | "LAYER3"`
          overrides the target layer explicitly.
        - Passing `hidden_layer_markdown` renders a bottom-anchored `LAYER · OVERLAY`
          stationery card onto `hidden_layer_name` (`LAYER1` by default, hidden until
          toggled visible).
        """
        render_style = RenderStyle(style)
        bg_style = BackgroundStyle(background)
        target_layer = (
            layer
            if layer is not None
            else ("BGLAYER" if render_style == RenderStyle.STYLIZED else "MAINLAYER")
        )
        if target_layer not in ALL_LAYERS:
            raise ValueError(f"layer must be one of {ALL_LAYERS}, got {target_layer!r}")

        effective_seed = seed if seed is not None else self._rng.randint(0, 1_000_000)
        renderer = MarkdownRenderer(
            style=render_style,
            background=bg_style,
            page_width=self.page_width,
            page_height=self.page_height,
            font_path=font_path,
            font_size=font_size,
            seed=effective_seed,
            extract_keywords=extract_keywords,
        )
        rendered_pages = renderer.render(markdown)

        hidden_rendered: list[RenderedPage] = []
        if hidden_layer_markdown:
            if hidden_layer_name not in ("LAYER1", "LAYER2", "LAYER3"):
                raise ValueError(
                    f"hidden_layer_name must be LAYER1, LAYER2, or LAYER3; got {hidden_layer_name!r}"
                )
            if target_layer == hidden_layer_name:
                raise ValueError(
                    f"layer {target_layer!r} conflicts with hidden_layer_name {hidden_layer_name!r}"
                )
            hidden_rendered = render_overlay_cards(
                hidden_layer_markdown,
                style=render_style,
                page_width=self.page_width,
                page_height=self.page_height,
                font_path=font_path,
                font_size=font_size,
                seed=effective_seed + 101,
            )

        total_pages_to_emit = max(len(rendered_pages), len(hidden_rendered))
        blank_fg = Image.new(
            "RGBA", (self.page_width, self.page_height), (255, 255, 255, 0)
        )
        paper_template = render_background(bg_style, self.page_width, self.page_height)
        start_page_offset = self._notebook.total_pages
        authored: list[AuthoredPageInfo] = []

        for idx in range(total_pages_to_emit):
            rpage = (
                rendered_pages[idx]
                if idx < len(rendered_pages)
                else RenderedPage(image=blank_fg, text="")
            )
            if page_dates is not None and idx < len(page_dates):
                page_dt: datetime | None = page_dates[idx]
            elif default_page_date is not None:
                page_dt = default_page_date + timedelta(seconds=idx)
            else:
                page_dt = None

            extra: dict[str, ExtraLayerSpec] = {}
            if idx < len(hidden_rendered):
                extra[hidden_layer_name] = ExtraLayerSpec(
                    image=hidden_rendered[idx].image,
                    visible=False,
                    white_is_transparent=False,
                )

            if target_layer == "BGLAYER":
                composited_bg = _composite_on_paper(paper_template, rpage.image)
                page_id = self.add_page(
                    background=bg_style,
                    custom_background=composited_bg,
                    custom_style_name=render_style.value,
                    background_visible=layer_visible,
                    extra_layers=extra or None,
                    created_at=page_dt,
                )
            elif target_layer == "MAINLAYER":
                page_id = self.add_page(
                    background=bg_style,
                    main_image=rpage.image if idx < len(rendered_pages) else None,
                    main_visible=layer_visible,
                    main_white_is_transparent=True,
                    extra_layers=extra or None,
                    created_at=page_dt,
                )
            else:
                extra[target_layer] = ExtraLayerSpec(
                    image=rpage.image,
                    visible=layer_visible,
                    white_is_transparent=True,
                )
                page_id = self.add_page(
                    background=bg_style,
                    extra_layers=extra,
                    created_at=page_dt,
                )

            abs_page_index = start_page_offset + idx

            if auto_toc:
                for h_span in rpage.headings:
                    self.add_title(
                        abs_page_index,
                        rect=h_span.rect,
                        level=h_span.level,
                        source_image=rpage.image,
                    )

            if extract_keywords:
                for kw_span in rpage.keywords:
                    self.add_keyword(
                        abs_page_index,
                        kw_span.keyword,
                        rect=kw_span.rect,
                    )

            if attach_links:
                for l_span in rpage.links:
                    if l_span.is_web_link:
                        self.add_web_link(
                            abs_page_index, l_span.target, rect=l_span.rect
                        )
                    elif (target_abs := l_span.target_page_index) is not None:
                        self._pending_page_links.append(
                            _PendingPageLink(
                                source_page_index=abs_page_index,
                                target_page_index=target_abs,
                                rect=l_span.rect,
                                raw_target=l_span.target,
                            )
                        )
                    elif (rel_offset := l_span.relative_page_offset) is not None:
                        self._pending_page_links.append(
                            _PendingPageLink(
                                source_page_index=abs_page_index,
                                target_page_index=abs_page_index + rel_offset,
                                rect=l_span.rect,
                                raw_target=l_span.target,
                            )
                        )
                    elif l_span.target.startswith("page:"):
                        raise ValueError(
                            f"Invalid page link target {l_span.target!r}; expected 1-based 'page:N' or relative 'page:+N'/'page:-N'"
                        )

            authored.append(
                AuthoredPageInfo(
                    page_index=abs_page_index,
                    page_id=page_id,
                    text=rpage.text,
                    headings=rpage.headings,
                    keywords=rpage.keywords,
                    links=rpage.links,
                )
            )

        return authored

    def add_keyword(
        self,
        page_index: int,
        keyword: str,
        *,
        rect: Rect = (88, 88, 240, 48),
    ) -> fileformat.Keyword:
        """Attach a searchable Supernote `Keyword` to `page_index` (0-based)."""
        if page_index < 0 or page_index >= self._notebook.total_pages:
            raise IndexError(f"page_index out of range: {page_index}")
        if not keyword or not keyword.strip():
            raise ValueError("keyword must be non-empty")
        if any(ch in keyword for ch in "<>\r\n"):
            raise ValueError(
                f"keyword cannot contain '<', '>', or newlines: {keyword!r}"
            )
        clamped = self._clamp_rect(rect)
        rect_str = f"{clamped[0]},{clamped[1]},{clamped[2]},{clamped[3]}"
        encoded_kw = keyword.encode("utf-8")
        kw_meta: dict[str, Any] = {
            "KEYWORDPAGE": str(page_index + 1),
            "KEYWORDSEQNO": "0",
            "KEYWORDRECT": rect_str,
            "KEYWORDRECTORI": rect_str,
            "KEYWORDSITE": "0",
            "KEYWORDLEN": str(len(encoded_kw)),
            "KEYWORD": keyword,
        }
        kw = fileformat.Keyword(kw_meta, content=encoded_kw)
        self._notebook.keywords.append(kw)
        return kw

    def _page_canvas_size(self, page_index: int) -> tuple[int, int]:
        if self._notebook.page(page_index).is_horizontal():
            return (self.page_height, self.page_width)
        return (self.page_width, self.page_height)

    def add_title(
        self,
        page_index: int,
        *,
        rect: Rect,
        level: int = 1,
        source_image: Image.Image | None = None,
    ) -> fileformat.Title:
        """Attach a Supernote TOC `Title` entry to `page_index` (0-based)."""
        if page_index < 0 or page_index >= self._notebook.total_pages:
            raise IndexError(f"page_index out of range: {page_index}")
        pw, ph = self._page_canvas_size(page_index)
        left, top, width, height = self._clamp_rect_for_size(rect, pw, ph)
        rect_str = f"{left},{top},{width},{height}"

        if source_image is not None:
            crop = source_image.crop((left, top, left + width, top + height))
            full_mask = Image.new("RGBA", (pw, ph), (255, 255, 255, 0))
            full_mask.paste(crop.convert("RGBA"), (left, top))
            title_bitmap = self._rle_encoder.encode(
                full_mask, white_is_transparent=True
            )
        else:
            title_bitmap = self._get_blank_rle(pw, ph)

        title_meta = {
            "TITLESEQNO": "0",
            "TITLELEVEL": str(max(1, min(3, level))),
            "TITLERECT": rect_str,
            "TITLERECTORI": rect_str,
            "TITLEBITMAP": "0",
            "TITLEPROTOCOL": "RATTA_RLE",
            "TITLESTYLE": "1000254",
        }
        title = fileformat.Title(
            title_meta, content=title_bitmap, page_number=page_index
        )
        self._notebook.titles.append(title)
        return title

    def add_web_link(
        self,
        page_index: int,
        url: str,
        *,
        rect: Rect = (88, 88, 300, 48),
    ) -> fileformat.Link:
        """Attach an outgoing web hyperlink (`TYPE_WEB_LINK`) to `page_index`."""
        if page_index < 0 or page_index >= self._notebook.total_pages:
            raise IndexError(f"page_index out of range: {page_index}")
        if not url or not url.strip():
            raise ValueError("url must be non-empty")
        pw, ph = self._page_canvas_size(page_index)
        left, top, width, height = self._clamp_rect_for_size(rect, pw, ph)
        rect_str = f"{left},{top},{width},{height}"
        encoded_url = base64.b64encode(url.encode("utf-8")).decode("ascii")
        link_meta = {
            "LINKTYPE": str(fileformat.Link.TYPE_WEB_LINK),
            "LINKINOUT": str(fileformat.Link.DIRECTION_OUT),
            "LINKRECT": rect_str,
            "LINKRECTORI": rect_str,
            "LINKBITMAP": "0",
            "LINKPROTOCOL": "RATTA_RLE",
            "LINKTIMESTAMP": self._created_at.strftime("%Y%m%d%H%M%S"),
            "LINKFILE": encoded_url,
            "LINKFILEID": "none",
            "PAGEID": "none",
        }
        link = fileformat.Link(
            link_meta,
            content=self._get_blank_rle(pw, ph),
            page_number=page_index,
        )
        self._notebook.links.append(link)
        return link

    def _build_page_link_object(
        self,
        notebook: fileformat.Notebook,
        page_index: int,
        target_page_index: int,
        *,
        rect: Rect,
    ) -> fileformat.Link:
        total = notebook.total_pages
        if page_index < 0 or page_index >= total:
            raise IndexError(f"page_index out of range: {page_index}")
        if target_page_index < 0 or target_page_index >= total:
            raise IndexError(f"target_page_index out of range: {target_page_index}")

        target_page_id = notebook.page(target_page_index).page_id
        if not target_page_id:
            raise exceptions.ManipulatorException(
                f"target page {target_page_index} is missing PAGEID"
            )
        pw, ph = (
            (self.page_height, self.page_width)
            if notebook.page(page_index).is_horizontal()
            else (self.page_width, self.page_height)
        )
        left, top, width, height = self._clamp_rect_for_size(rect, pw, ph)
        rect_str = f"{left},{top},{width},{height}"
        encoded_path = base64.b64encode(b"internal.note").decode("ascii")
        link_meta = {
            "LINKTYPE": str(fileformat.Link.TYPE_PAGE_LINK),
            "LINKINOUT": str(fileformat.Link.DIRECTION_OUT),
            "LINKRECT": rect_str,
            "LINKRECTORI": rect_str,
            "LINKBITMAP": "0",
            "LINKPROTOCOL": "RATTA_RLE",
            "LINKTIMESTAMP": self._created_at.strftime("%Y%m%d%H%M%S"),
            "LINKFILE": encoded_path,
            "LINKFILEID": self.file_id,
            "PAGEID": target_page_id,
        }
        return fileformat.Link(
            link_meta,
            content=self._get_blank_rle(pw, ph),
            page_number=page_index,
        )

    def add_page_link(
        self,
        page_index: int,
        target_page_index: int,
        *,
        rect: Rect = (88, 88, 300, 48),
    ) -> fileformat.Link:
        """Attach an internal notebook page jump link (`TYPE_PAGE_LINK`)."""
        link = self._build_page_link_object(
            self._notebook, page_index, target_page_index, rect=rect
        )
        self._notebook.links.append(link)
        return link

    def _build_export_notebook(self) -> fileformat.Notebook:
        if self._notebook.total_pages == 0 and not self._pending_page_links:
            empty_clone = copy.deepcopy(self)
            empty_clone.add_page()
            return empty_clone._notebook

        if not self._pending_page_links:
            return self._notebook

        total = self._notebook.total_pages
        export_nb = copy.copy(self._notebook)
        export_nb.links = list(self._notebook.links)
        for item in self._pending_page_links:
            if item.target_page_index < 0 or item.target_page_index >= total:
                label = item.raw_target or f"page:{item.target_page_index + 1}"
                raise ValueError(
                    f"Pending page link {label!r} on page {item.source_page_index + 1} resolves to out-of-range page {item.target_page_index + 1} (notebook has {total} pages)"
                )
            export_nb.links.append(
                self._build_page_link_object(
                    export_nb,
                    item.source_page_index,
                    item.target_page_index,
                    rect=item.rect,
                )
            )
        return export_nb

    def to_bytes(self) -> bytes:
        """Pack the authored notebook into validated binary `.note` bytes."""
        return reconstruct(self._build_export_notebook())

    def to_notebook(self) -> fileformat.Notebook:
        """Build and return a parsed `Notebook` with finalized offsets and metadata."""
        raw = self.to_bytes()
        return load(io.BytesIO(raw))

    def save(self, path: str | os.PathLike[str]) -> Path:
        """Write the authored `.note` binary to disk and return the `Path`."""
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.to_bytes())
        return dest

    @staticmethod
    def _make_layer_meta(
        layer_name: str,
        *,
        protocol: schema.LayerProtocol = schema.LayerProtocol.RATTA_RLE,
    ) -> dict[str, Any]:
        return {
            "LAYERTYPE": "NOTE",
            "LAYERPROTOCOL": protocol.value,
            "LAYERNAME": layer_name,
            "LAYERPATH": "0",
            "LAYERBITMAP": "0",
            "LAYERVECTORGRAPH": "0",
            "LAYERRECOGN": "0",
        }

    @staticmethod
    def _fit_layer_image(image: Image.Image, width: int, height: int) -> Image.Image:
        canvas = Image.new("RGBA", (width, height), (255, 255, 255, 0))
        fitted = image.copy()
        fitted.thumbnail((width, height), Image.Resampling.LANCZOS)
        ox = (width - fitted.width) // 2
        oy = (height - fitted.height) // 2
        rgba = fitted.convert("RGBA")
        canvas.alpha_composite(rgba, dest=(ox, oy))
        return canvas

    @staticmethod
    def _clamp_rect_for_size(rect: Rect, max_w: int, max_h: int) -> Rect:
        left, top, width, height = rect
        clamped_left = max(0, min(max_w - 4, int(left)))
        clamped_top = max(0, min(max_h - 4, int(top)))
        clamped_w = max(4, min(max_w - clamped_left, int(width)))
        clamped_h = max(4, min(max_h - clamped_top, int(height)))
        return (clamped_left, clamped_top, clamped_w, clamped_h)

    def _clamp_rect(self, rect: Rect) -> Rect:
        return self._clamp_rect_for_size(rect, self.page_width, self.page_height)


def create_notebook(
    markdown: str = "",
    *,
    style: RenderStyle | str = RenderStyle.STYLIZED,
    background: BackgroundStyle | str = BackgroundStyle.WHITE,
    layer: str | None = None,
    hidden_layer_markdown: str | None = None,
    equipment: str = "N6",
    auto_toc: bool = False,
    extract_keywords: bool = True,
    font_path: str | os.PathLike[str] | None = None,
    font_size: int | None = None,
    seed: int = 0,
    created_at: datetime | None = None,
) -> bytes:
    """One-shot convenience helper to author a complete `.note` binary from Markdown.

    Args:
        markdown: Markdown / Bullet Journal Rapid-Logging document. If empty, creates
            a single blank stationery page using `background`.
        style: Visual preset (`"stylized"`, `"handwriting"`, or `"architect"`).
        background: Paper template (`"white"`, `"dots"`, `"ruled"`, or `"grid"`).
        layer: Optional explicit layer override (`"BGLAYER"`, `"MAINLAYER"`, `"LAYER1"`..`"LAYER3"`).
        hidden_layer_markdown: Optional Markdown rendered onto a hidden `LAYER1` overlay card.
        equipment: Device profile (`"N6"` for `1404x1872` Nomad, `"N5"` for `1920x2560` Manta).
        auto_toc: When `True`, promotes rendered `#`–`###` headings into Supernote TOC `Title` blocks.
        extract_keywords: When `True`, attaches `#hashtag` tokens as searchable `Keyword` blocks.
        font_path: Optional path to a custom `.ttf`/`.otf` typeface.
        font_size: Optional base body font size in pixels.
        seed: Deterministic RNG seed controlling handwriting pressure/jitter.
        created_at: Optional base UTC timestamp embedded into generated `FILE_ID` and `PAGEID`s.

    Returns:
        Complete `.note` binary payload as `bytes`.
    """
    author = NotebookAuthor(
        equipment=equipment,
        created_at=created_at,
        seed=seed,
    )
    if markdown:
        author.add_markdown(
            markdown,
            style=style,
            background=background,
            layer=layer,
            hidden_layer_markdown=hidden_layer_markdown,
            auto_toc=auto_toc,
            extract_keywords=extract_keywords,
            font_path=font_path,
            font_size=font_size,
            seed=seed,
        )
    else:
        author.add_page(background=background)
    return author.to_bytes()
