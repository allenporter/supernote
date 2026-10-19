"""Tests for `supernote.server.ai.base`."""

from __future__ import annotations

from supernote.server.ai.base import AIError


def test_ai_error_is_runtime_error() -> None:
    err = AIError("backend failure")
    assert isinstance(err, RuntimeError)
    assert str(err) == "backend failure"
