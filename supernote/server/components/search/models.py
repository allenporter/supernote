"""Pure domain result models for the `search` vertical component.

Defines the transport-free, database-free dataclasses returned by
`supernote.server.components.search.service.SearchService`:

- `SearchResult`: Ranked page match returned by `SearchService.search_chunks`.
- `NotebookInfo`: Active `.note` summary returned by `SearchService.list_notebooks`.

Because this module has zero SQLAlchemy, `aiohttp`, or AI-backend imports,
transport platforms (`http.py`, future `mcp.py`) and sibling components can
import these types without introducing runtime coupling.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "NotebookInfo",
    "SearchResult",
]


@dataclass(slots=True)
class SearchResult:
    """Single ranked page hit returned by semantic search."""

    file_id: int
    """VFS file identifier (`UserFileDO.id`) of the matching notebook."""

    file_name: str
    """Filename of the matching `.note` file."""

    page_index: int
    """Zero-based page index within the notebook."""

    page_id: str
    """Supernote page identifier (`PAGEID`) from the notebook metadata."""

    score: float
    """Cosine similarity score between query and page embeddings."""

    text_preview: str
    """Up to 200-character preview of the page's OCR text content."""

    date: str | None = None
    """Optional inferred page date formatted as `YYYY-MM-DD`, if determinable."""


@dataclass(slots=True)
class NotebookInfo:
    """Summary metadata for an active `.note` file."""

    file_id: int
    """VFS file identifier (`UserFileDO.id`)."""

    file_name: str
    """Filename of the `.note` file."""

    create_time: int
    """Creation timestamp in milliseconds since Unix epoch."""

    update_time: int
    """Last modification timestamp in milliseconds since Unix epoch."""
