# Supernote notebook parsing and conversion

This package provides tools for parsing and converting Supernote `.note` files. It originally started as a fork of [supernote-tool](https://github.com/jya-dev/supernote-tool) with lighter dependencies, modern type hints, and expanded test coverage.

## Usage

### Parsing a Notebook

```python
from supernote.notebook import parse_notebook

notebook = parse_notebook("path/to/note.note")
```

### Converting to Formats

Use the built-in converters (`PdfConverter`, `ImageConverter`, `SvgConverter`, `TextConverter`) to convert notebook pages:

```python
from pathlib import Path
from supernote.notebook import ImageConverter, PdfConverter, SvgConverter

# Convert all pages (-1) or a specific page index to PDF
pdf_data = PdfConverter(notebook).convert(-1)
Path("output.pdf").write_bytes(pdf_data)

# Convert first page to PNG (PIL Image)
image = ImageConverter(notebook).convert(0)
image.save("page1.png")

# Convert first page to SVG
svg_string = SvgConverter(notebook).convert(0)
```

### Accessing Metadata

You can access metadata and structure directly:

```python
# Total pages
print(notebook.total_pages)

# Page ID
print(notebook.page(0).page_id)

# Keywords
for keyword in notebook.keywords:
    print(keyword.keyword)
```

## Advanced Usage

For more control, you can use specific converters directly:

```python
from supernote.notebook import PdfConverter

converter = PdfConverter(notebook)
pdf_data = converter.convert(0)  # Convert specific page
```

## Authoring, Rendering & Cooperative Editing APIs

`supernote.notebook` exposes **four layered APIs** so callers can work at the exact level of abstraction they need—without coupling visual typography, `.note` binary framing, or test-fixture generation together:

| Tier | Entry Points | When to Use |
| :--- | :--- | :--- |
| **1. One-Shot Authoring** | `create_notebook()` | Convert a Markdown / Bullet Journal string directly into valid `.note` bytes in one call. |
| **2. Multi-Page & Cooperative Builder** | `NotebookAuthor`, `ExtraLayerSpec`, `AuthoredPageInfo` | Build multi-page notebooks, mix Markdown spreads with custom PIL images, target specific layers (`BGLAYER`, `MAINLAYER`, `LAYER1`–`LAYER3`), attach TOC `Title`s / `Keyword`s / `Link`s, or **append pages onto an existing `.note` file** (`NotebookAuthor.from_notebook()`) while preserving existing strokes and real-time recognition (`RECOGNTEXT`). |
| **3. Pure Layout & Intrinsic Spans** | `render_markdown()`, `MarkdownRenderer`, `render_background()`, `RenderedPage` | Paginate Markdown into transparent RGBA PIL images + plain-text ground-truth transcripts + pixel bounding boxes (`HeadingSpan`, `KeywordSpan`, `LinkSpan`) without packing a `.note` file. |
| **4. Low-Level Layer Codecs** | `RattaRleX2Encoder`, `RattaRleEncoder`, `PngEncoder` | Compress raw PIL images into X1 4-shade or X2 240-shade anti-aliased `RATTA_RLE` bitmaps or MD5-indexed `user_*` PNG templates. |

*(For deterministic server/OCR/sync E2E tests, see `supernote.testing.build_synthetic_notebook()` and `append_synthetic_page()`; for shell & agent workflows, use `supernote create`.)*

### Design Philosophy: Cooperative Human + Agent Layers

Physical Supernote stylus strokes live on `MAINLAYER`. When a script or AI agent generates or edits a notebook that a human will also write in on-device, layer routing keeps both workflows non-destructive:

1. **Templates on `BGLAYER` (`style="stylized"` default)**: Editorial planners, briefings, and habit trackers render onto `BGLAYER` as a custom `user_stylized` PNG template, leaving `MAINLAYER` 100% empty so human pen strokes, erasers, and lasso moves never collide with the template.
2. **Simulated Ink on `MAINLAYER` (`style="handwriting"` / `"architect"` default)**: Encodes variable-weight anti-aliased `RATTA_RLE` ink onto `MAINLAYER` over native `style_*` paper (`dots`, `ruled`, `grid`) for realistic synthetic handwriting and standalone notes.
3. **Toggleable Overlays on `LAYER1`–`LAYER3` (`hidden_layer_markdown`)**: Places flashcard answer keys, coaching prompts, or review cards onto a hidden secondary layer (`isVisible: False` by default) that can be revealed on-device via the Layers menu or in Python via `build_visibility_overlay(layer1=VisibilityOverlay.VISIBLE)`.

### Authoring Examples

```python
from pathlib import Path
from supernote.notebook import NotebookAuthor, create_notebook, load_notebook

# 1. One-shot Bullet Journal spread -> .note bytes
note_bytes = create_notebook(
    "#### NOV 2026 · DAILY LOG\n"
    "# Focus & Rapid Log\n\n"
    "* - [ ] Ship ==notebook API== #roadmap\n"
    "- [>] Migrate soak test\n"
    "! - [-] Quiet stationery grids let ink command hierarchy",
    style="stylized",   # "stylized" (editorial), "handwriting" (Caveat script), or "architect"
    background="dots",  # "white", "dots", "ruled", or "grid"
    auto_toc=True,
)
Path("daily.note").write_bytes(note_bytes)

# 2. Multi-page builder with simulated handwriting + hidden LAYER1 answer card
author = NotebookAuthor(equipment="N6", seed=42)
pages = author.add_markdown(
    "# Practice Quiz\n\n1. What is 6 * 7? [See Formula Sheet](page:2)\n\n---\n\n# Formula Sheet",
    style="handwriting",
    background="ruled",
    hidden_layer_markdown="### Answer Key\n\n- [-] 42",
    auto_toc=True,
)
author.save("quiz.note")

# 3. Non-destructively append an agent summary page onto an existing .note file
existing = load_notebook("meeting_notes.note")
editor = NotebookAuthor.from_notebook(existing)
editor.add_markdown("# Action Items\n\n* - [ ] Follow up on Q4 budget #finance", style="stylized")
editor.save("meeting_notes_updated.note")
```
