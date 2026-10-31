"""
.. include:: ../README.md
"""

import importlib
from typing import Any

__all__ = [
    "cli",
    "client",
    "models",
    "notebook",
    "server",
]


def __getattr__(name: str) -> Any:
    """Lazily import top-level subpackages on first attribute access (PEP 562).

    @private

    Python executes `supernote/__init__.py` whenever any subpackage (such as
    `supernote.server`, `supernote.client`, or `supernote.notebook`) is imported.
    Deferring subpackage imports until accessed avoids pulling in unrelated
    subpackages and their heavy dependencies (e.g. SQLAlchemy/aiohttp when
    using the notebook parser, or client modules when running the server),
    Then caches the loaded module in `globals()` so subsequent attribute lookups
    have zero overhead.
    """
    if name in __all__:
        module = importlib.import_module(f".{name}", __name__)
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
