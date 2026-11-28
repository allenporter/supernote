"""Notebook summary (Digest) vertical server component (`SummaryComponent`).

In Supernote Private Cloud, *summaries* (known as **Digests** on Supernote devices
and in the Partner App) are structured excerpts, comments, and handwritten
annotations linked to notebooks, organized into categories (**summary groups**) and
**summary tags**. This component manages both device-authored Digests and
server-generated AI syntheses produced after notebook OCR completes (stored under the
shared `"AI Summaries"` Digest category).

### Responsibilities

- `service.py` (`SummaryService`): Persists summaries, groups, and tags (`SummaryDO`,
  `SummaryTagDO`), runs a periodic retention purge loop for soft-deleted rows, and
  emits summary domain and blob-cleanup events.
- `http.py` (`"http"` platform): Serves the Supernote summary synchronization
  protocol (`/api/file/*/summary*`), signed handwriting blob upload/download URLs,
  the extended Web UI listing endpoint (`POST /api/extended/file/summary/list`), and
  handwriting PDF/PNG renders (`POST /api/extended/file/summary/to/pdf|png`).
- `processor.py` (`"processor"` platform): Contributes `SummaryModule`, the
  post-OCR pipeline stage that aggregates notebook transcripts and upserts AI
  summaries via `SummaryModel`.

### Internal Python API for Sibling Components & Plugins

Components that read or mutate summaries should declare ``dependencies = ("summary",)``
and access the typed service key:

```python
from supernote.server.components.summary import SUMMARY_SERVICE_KEY

summaries = core.app[SUMMARY_SERVICE_KEY]
items = await summaries.list_summaries_for_file_internal(user_email, file_id)
```

### Lifecycle

1. `async_setup`: Instantiates `SummaryService` bound to `core.user_service`,
   `core.session_manager`, and `core.event_bus`, exposing it via
   `core.app[SUMMARY_SERVICE_KEY]`.
2. `async_start`: Starts the periodic soft-delete expiration purge loop.
3. `async_stop`: Idempotently stops the purge loop and releases the service reference.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from aiohttp import web

from supernote.server.core import ServerCore

from .config import SummaryConfig
from .service import SUMMARY_SERVICE_KEY, SummaryService

SUMMARY_CONFIG_KEY: web.AppKey[SummaryConfig] = web.AppKey("summary_config")
"""Typed `aiohttp.web.AppKey` exposing validated `SummaryConfig` to platform modules."""

__all__ = [
    "SUMMARY_CONFIG_KEY",
    "SUMMARY_SERVICE_KEY",
    "SummaryComponent",
    "SummaryConfig",
    "SummaryService",
]


class SummaryComponent:
    """Vertical component managing summaries, groups, tags, HTTP routes, and AI summarization."""

    domain = "summary"
    dependencies: tuple[str, ...] = ("ai", "conversion", "transcript")
    platforms: tuple[str, ...] = ("http", "mcp", "processor")

    def __init__(self) -> None:
        self._config: SummaryConfig | None = None
        self._service: SummaryService | None = None
        self._unregister_blob_provider: Callable[[], None] | None = None

    @property
    def config(self) -> SummaryConfig | None:
        """Validated `SummaryConfig` after `async_setup`."""
        return self._config

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Validate `SummaryConfig`, instantiate `SummaryService`, and register blob-reference hook."""
        self._config = SummaryConfig.from_dict(dict(config))
        service = SummaryService(
            core.user_service,
            core.session_manager,
            core.event_bus,
        )
        core.app[SUMMARY_CONFIG_KEY] = self._config
        core.app[SUMMARY_SERVICE_KEY] = service
        self._service = service
        self._unregister_blob_provider = (
            core.file_service.register_blob_reference_provider(
                SummaryService.get_referenced_blob_keys
            )
        )

    async def async_start(self, core: ServerCore) -> None:
        """Start periodic hard-deletion of expired soft-deleted summaries."""
        assert self._service is not None
        await self._service.start()

    async def async_stop(self, core: ServerCore) -> None:
        """Idempotently stop the summary purge loop and release references."""
        if self._unregister_blob_provider is not None:
            self._unregister_blob_provider()
            self._unregister_blob_provider = None
        if self._service is not None:
            await self._service.stop()
            self._service = None
