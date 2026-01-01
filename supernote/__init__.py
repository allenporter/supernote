"""
.. include:: ../README.md
"""

# Core notebook parsing (always available)
from . import notebook  # noqa: F401

__all__ = [
    "models",
]

# Optional: Client library
try:
    from . import client  # noqa: F401

    __all__.extend(["client"])
except ImportError:
    pass

# Optional: Server
try:
    from . import server  # noqa: F401

    __all__.extend(["server"])
except ImportError:
    pass

__all__.extend(["notebook"])
