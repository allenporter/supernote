"""Unit tests for `supernote.server.components.transcript.models`."""

from __future__ import annotations

from supernote.server.components.transcript.models import PageTranscript


def test_page_transcript_defaults() -> None:
    """Verify PageTranscript defaults optional text and date to None."""
    page = PageTranscript(page_index=0, page_id="P1")
    assert page.page_index == 0
    assert page.page_id == "P1"
    assert page.text is None
    assert page.date is None
