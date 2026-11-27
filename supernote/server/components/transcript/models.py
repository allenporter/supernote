"""Pure domain result models for the `transcript` vertical component.

Defines the transport-free, database-free dataclasses returned by
`supernote.server.components.transcript.service.TranscriptService`:

- `PageTranscript`: Structured per-page OCR transcript returned by
  `TranscriptService.get_page_transcripts`.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "PageTranscript",
]


@dataclass(slots=True)
class PageTranscript:
    """Structured OCR transcript for a single notebook page."""

    page_index: int
    """Zero-based page index within the notebook."""

    page_id: str
    """Supernote page identifier (`PAGEID`)."""

    text: str | None = None
    """Transcribed page text, or `None` if no text was extracted."""

    date: str | None = None
    """Optional inferred page date formatted as `YYYY-MM-DD`, if determinable."""
