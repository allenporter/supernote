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

from supernote.server.components.ai import OCR_MODEL_KEY
from supernote.server.components.conversion import CONVERSION_SERVICE_KEY
from supernote.server.core import ServerCore

from .models import PageTranscript, SummaryTranscript
from .service import TRANSCRIPT_SERVICE_KEY, TranscriptService
from .summary_ocr import SummaryOcrRunner

__all__ = [
    "TRANSCRIPT_SERVICE_KEY",
    "PageTranscript",
    "SummaryOcrRunner",
    "SummaryTranscript",
    "TranscriptComponent",
    "TranscriptService",
]


class TranscriptComponent:
    """Vertical component managing formatted and per-page OCR transcript retrieval."""

    domain = "transcript"
    dependencies: tuple[str, ...] = ("ai", "conversion", "note_metadata")
    platforms: tuple[str, ...] = ("http", "mcp", "processor")

    def __init__(self) -> None:
        self._summary_ocr_runner: SummaryOcrRunner | None = None

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Instantiate `TranscriptService` and `SummaryOcrRunner`, exposing `TRANSCRIPT_SERVICE_KEY`."""
        transcript_service = TranscriptService(
            core.session_manager,
            event_bus=core.event_bus,
        )
        core.app[TRANSCRIPT_SERVICE_KEY] = transcript_service
        self._summary_ocr_runner = SummaryOcrRunner(
            session_manager=core.session_manager,
            blob_storage=core.blob_storage,
            conversion_service=core.app[CONVERSION_SERVICE_KEY],
            transcript_service=transcript_service,
            event_bus=core.event_bus,
            ocr_model_getter=lambda: core.app.get(OCR_MODEL_KEY),
        )

    async def async_start(self, core: ServerCore) -> None:
        """Start background OCR subscription for handwritten Digest annotations."""
        if self._summary_ocr_runner is not None:
            await self._summary_ocr_runner.start()

    async def async_stop(self, core: ServerCore) -> None:
        """Idempotently stop and drain any in-flight summary handwriting OCR tasks."""
        runner = self._summary_ocr_runner
        self._summary_ocr_runner = None
        if runner is not None:
            await runner.stop()
