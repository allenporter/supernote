"""Pure domain result models for the `transcript` vertical component.

Defines the transport-free, database-free dataclasses returned by
`supernote.server.components.transcript.service.TranscriptService`:

- `PageTranscript`: Structured per-page OCR transcript returned by
  `TranscriptService.get_page_transcripts`.
- `SummaryTranscript`: Stored OCR transcript for a handwritten Digest summary
  annotation returned by `TranscriptService.get_summary_transcript`,
  `get_summary_transcripts`, and `upsert_summary_transcript`.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "PageTranscript",
    "SummaryTranscript",
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


@dataclass(slots=True)
class SummaryTranscript:
    """Stored OCR transcript for a Digest summary's handwritten annotation."""

    summary_id: int
    """Numeric ID of the `SummaryDO`."""

    handwrite_md5: str
    """MD5 hash of the `.mark` handwriting blob that produced `text`."""

    text: str
    """Transcribed handwriting text (empty string if blank or illegible)."""

    model_id: str | None = None
    """Optional identifier of the OCR model that produced `text`."""

    create_time: int = 0
    """Creation timestamp in epoch milliseconds."""

    update_time: int = 0
    """Last update timestamp in epoch milliseconds."""
