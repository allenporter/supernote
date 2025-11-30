"""Supernote notebook parsing and conversion.

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

from .parser import load_notebook, load, parse_metadata
from .fileformat import (
    Notebook,
    SupernoteMetadata,
    Page,
    Layer,
    Cover,
    Keyword,
    Title,
    Link,
)
from .converter import (
    PngConverter,
    SvgConverter,
    PdfConverter,
    TextConverter,
    ImageConverter,
    VisibilityOverlay,
)
from .color import ColorPalette, MODE_RGB
from .manipulator import reconstruct, merge

# Alias for convenience
parse_notebook = load_notebook

__all__ = [
    "parse_notebook",
    "load_notebook",
    "load",
    "parse_metadata",
    "Notebook",
    "SupernoteMetadata",
    "Page",
    "Layer",
    "Cover",
    "Keyword",
    "Title",
    "Link",
    "PngConverter",
    "SvgConverter",
    "PdfConverter",
    "TextConverter",
    "ImageConverter",
    "VisibilityOverlay",
    "ColorPalette",
    "MODE_RGB",
    "reconstruct",
    "merge",
]
