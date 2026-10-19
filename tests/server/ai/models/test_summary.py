"""Tests for `supernote.server.ai.models.summary`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from supernote.server.ai.models.fake.summary import FakeSummaryModel
from supernote.server.ai.models.summary import (
    ConcurrencyLimitedSummaryModel,
    create_summary_model,
)
from supernote.server.config import AuthConfig, ServerConfig


def test_create_summary_model(tmp_path: Path) -> None:
    config = ServerConfig(
        auth=AuthConfig(secret_key="secret"),
        storage_dir=str(tmp_path),
    )
    assert create_summary_model(config) is None

    with patch("google.genai.Client"):
        config.gemini_api_key = "test-key"
        model = create_summary_model(config)
        assert isinstance(model, ConcurrencyLimitedSummaryModel)
        assert model.model_id == config.gemini_ocr_model


async def test_concurrency_limited_summary_model() -> None:
    wrapped = ConcurrencyLimitedSummaryModel(FakeSummaryModel(), max_concurrency=2)
    result = await wrapped.summarize("TRANSCRIPT:\nHello")
    assert wrapped.model_id == "fake-summary-v1"
    assert len(result.segments) == 1
