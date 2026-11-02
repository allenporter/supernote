"""Supernote `.note` parsing, conversion, Bullet Journal rendering, and binary authoring.

API Overview (Choosing the Right Entry Point)
---------------------------------------------
- **Read & Convert Existing Notebooks**:
  - `load_notebook(path)` / `load(stream)` -> `Notebook`
  - `ImageConverter`, `PdfConverter`, `SvgConverter`, `TextConverter`
- **One-Shot Markdown -> `.note` Authoring**:
  - `create_notebook(markdown, style=..., background=...)` -> `bytes`
- **Multi-Page Builder & Non-Destructive Appending**:
  - `NotebookAuthor()` or `NotebookAuthor.from_notebook(existing)`
  - `.add_markdown(...)`, `.add_page(...)`, `.add_title(...)`, `.add_keyword(...)`,
    `.add_web_link(...)`, `.add_page_link(...)` -> `.save(path)` / `.to_bytes()`
- **Pure Visual Rendering & Ground-Truth Bounding Boxes (No `.note` Packing)**:
  - `render_markdown(...)` / `MarkdownRenderer` -> `list[RenderedPage]`
  - `render_background(...)` -> PIL `Image`
- **Low-Level Binary Layer Compression**:
  - `RattaRleX2Encoder`, `RattaRleEncoder`, `PngEncoder`
- **Binary Manipulation**:
  - `reconstruct(notebook)`, `merge(note1, note2)`

.. include:: ./README.md
"""

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

from . import exceptions, schema
from .author import (
    AuthoredPageInfo,
    ExtraLayerSpec,
    NotebookAuthor,
    create_notebook,
    generate_supernote_id,
)
from .color import MODE_RGB, ColorPalette
from .converter import (
    ImageConverter,
    PdfConverter,
    PngConverter,
    SvgConverter,
    TextConverter,
    VisibilityOverlay,
    build_visibility_overlay,
)
from .encoder import PngEncoder, RattaRleEncoder, RattaRleX2Encoder
from .fileformat import (
    Cover,
    Keyword,
    Layer,
    Link,
    Notebook,
    Page,
    Title,
)
from .manipulator import merge, reconstruct
from .parser import load, load_notebook, parse_metadata
from .renderer import (
    BackgroundStyle,
    HeadingSpan,
    KeywordSpan,
    LinkSpan,
    MarkdownRenderer,
    RenderedPage,
    RenderStyle,
    get_pagestyle_name,
    get_template_line_spacing,
    render_background,
    render_markdown,
    render_overlay_cards,
)
from .schema import SupernoteMetadata

# Alias for convenience
parse_notebook = load_notebook

__all__ = [
    "MODE_RGB",
    "AuthoredPageInfo",
    "BackgroundStyle",
    "ColorPalette",
    "Cover",
    "ExtraLayerSpec",
    "HeadingSpan",
    "ImageConverter",
    "Keyword",
    "KeywordSpan",
    "Layer",
    "Link",
    "LinkSpan",
    "MarkdownRenderer",
    "Notebook",
    "NotebookAuthor",
    "Page",
    "PdfConverter",
    "PngConverter",
    "PngEncoder",
    "RattaRleEncoder",
    "RattaRleX2Encoder",
    "RenderStyle",
    "RenderedPage",
    "SupernoteMetadata",
    "SvgConverter",
    "TextConverter",
    "Title",
    "VisibilityOverlay",
    "build_visibility_overlay",
    "create_notebook",
    "exceptions",
    "generate_supernote_id",
    "get_pagestyle_name",
    "get_template_line_spacing",
    "load",
    "load_notebook",
    "merge",
    "parse_metadata",
    "parse_notebook",
    "reconstruct",
    "render_background",
    "render_markdown",
    "render_overlay_cards",
    "schema",
]
