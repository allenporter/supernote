"""Tests for `supernote.server.components.fake_ai.ocr`."""

from __future__ import annotations

from supernote.server.components.fake_ai.ocr import FakeOcrModel


async def test_fake_ocr_model() -> None:
    ocr_model = FakeOcrModel()
    text = await ocr_model.extract_text(b"png", "Transcribe this page.")
    assert text == "Transcribed (3 bytes)"
    assert ocr_model.calls == [(b"png", "Transcribe this page.")]
