"""Supernote toolkit for parsing, cloud access, and self-hosting.

.. include:: ../README.md
"""

__version__ = "0.4.0"

# Core notebook parsing (always available)
from .notebook import (
    parse_notebook,
    load_notebook,
    load,
    parse_metadata,
    Notebook,
    PngConverter,
    SvgConverter,
    PdfConverter,
    TextConverter,
    ImageConverter,
    VisibilityOverlay,
    ColorPalette,
    MODE_RGB,
    reconstruct,
    merge,
)

# Expose submodules for convenience (e.g. sn.color)
from .notebook import color
from .notebook import converter

__all__ = [
    "notebook",
    "parse_notebook",
    "load_notebook",
    "load",
    "parse_metadata",
    "Notebook",
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
    "color",
    "converter",
]

# Optional: Cloud client
try:
    from . import cloud  # noqa: F401

    __all__.extend(["cloud"])
except ImportError:
    pass

# Optional: Server
try:
    from . import server  # noqa: F401

    __all__.extend(["server"])
except ImportError:
    pass
