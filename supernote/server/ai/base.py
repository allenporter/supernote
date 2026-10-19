"""Common error handling for AI models.

All AI model backends translate vendor SDK failures and malformed model
responses into `AIError` so callers can handle model failures uniformly without
depending on vendor-specific exception types.
"""

from __future__ import annotations

__all__ = [
    "AIError",
]


class AIError(RuntimeError):
    """Raised when an AI model backend fails or returns an invalid response."""
