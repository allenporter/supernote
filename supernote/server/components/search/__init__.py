"""Semantic search vertical server component (`SearchComponent`).

Owns `SearchService`, pure result models (`SearchResult`, `NotebookInfo`),
and the HTTP search endpoint (`POST /api/extended/search`).

### Internal Python API for Sibling Components & Plugins

Components that run semantic search across notebooks should declare
``dependencies = ("search",)`` and access the typed service key:

```python
from supernote.server.components.search import SEARCH_SERVICE_KEY

search = core.app[SEARCH_SERVICE_KEY]
hits = await search.search_chunks(user_id=user_id, query="project roadmap")
```

### Lifecycle & Embedding Model Handoff

1. `async_setup`: Instantiates `SearchService` bound to `core.session_manager`
   and any pre-configured `core.app.get(EMBEDDING_MODEL_KEY)`, exposing it on
   `core.app[SEARCH_SERVICE_KEY]`.
2. `async_start`: Binds the embedding model resolved by `AiRegistrar` during
   startup (`core.app.get(EMBEDDING_MODEL_KEY)`) onto `SearchService`.
3. `async_stop`: Idempotently clears the component's service reference.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore
from supernote.server.keys import EMBEDDING_MODEL_KEY

from .models import NotebookInfo, SearchResult
from .service import SEARCH_SERVICE_KEY, SearchService

__all__ = [
    "SEARCH_SERVICE_KEY",
    "NotebookInfo",
    "SearchComponent",
    "SearchResult",
    "SearchService",
]


class SearchComponent:
    """Vertical component managing semantic search, notebook listing, and transcripts."""

    domain = "search"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("http", "mcp")

    def __init__(self) -> None:
        self._service: SearchService | None = None

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Instantiate `SearchService` and expose it via `SEARCH_SERVICE_KEY`."""
        service = SearchService(
            core.session_manager,
            core.app.get(EMBEDDING_MODEL_KEY),
        )
        core.app[SEARCH_SERVICE_KEY] = service
        self._service = service

    async def async_start(self, core: ServerCore) -> None:
        """Bind the resolved embedding model onto `SearchService` once AI platforms load."""
        assert self._service is not None
        if (embedding_model := core.app.get(EMBEDDING_MODEL_KEY)) is not None:
            self._service.embedding_model = embedding_model

    async def async_stop(self, core: ServerCore) -> None:
        """Idempotently release the component's service reference."""
        self._service = None
