"""Notebook transcript vertical server component (`TranscriptComponent`).

Owns `TranscriptService`, `PageTranscript`, and the HTTP transcript endpoint
(`POST /api/extended/transcript`). Independent of AI embedding models and
search ranking.

### Internal Python API for Sibling Components & Plugins

Components that read notebook transcripts (for example, MCP retrieval tools,
exporters, or RAG workflows) should declare ``dependencies = ("transcript",)``
and access the typed service key:

```python
from supernote.server.components.transcript import TRANSCRIPT_SERVICE_KEY

transcripts = core.app[TRANSCRIPT_SERVICE_KEY]
text = await transcripts.get_transcript(user_id=user_id, file_id=file_id)
```
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

from .models import PageTranscript
from .service import TRANSCRIPT_SERVICE_KEY, TranscriptService

__all__ = [
    "TRANSCRIPT_SERVICE_KEY",
    "PageTranscript",
    "TranscriptComponent",
    "TranscriptService",
]


class TranscriptComponent:
    """Vertical component managing formatted and per-page OCR transcript retrieval."""

    domain = "transcript"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("http", "mcp")

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Instantiate `TranscriptService` and expose it via `TRANSCRIPT_SERVICE_KEY`."""
        core.app[TRANSCRIPT_SERVICE_KEY] = TranscriptService(core.session_manager)

    async def async_start(self, core: ServerCore) -> None:
        """No-op; transcript operations are driven on demand by callers."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; transcript service holds no background tasks."""
