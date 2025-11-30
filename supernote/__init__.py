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
    "__version__",
    # Notebook
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
    from .cloud import CloudClient, login_client  # noqa: F401

    __all__.extend(["CloudClient", "login_client"])
except ImportError:
    pass

# Optional: Server
try:
    from .server import create_app, run  # noqa: F401

    __all__.extend(["create_app", "run"])
except ImportError:
    pass
