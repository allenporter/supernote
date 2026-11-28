"""Tests for `supernote.server.components.summary.config`."""

from __future__ import annotations

import pytest

from supernote.server.components.summary.config import SummaryConfig


def test_summary_config_defaults() -> None:
    cfg = SummaryConfig.from_dict({})
    assert cfg.enabled is True
    assert cfg.max_pages_per_chunk == 8
    assert cfg.max_chars_per_chunk == 16_000
    assert cfg.incremental is True
    assert cfg.carry_over_context is True


def test_summary_config_allows_zero_pages_to_disable_chunking() -> None:
    cfg = SummaryConfig.from_dict({"max_pages_per_chunk": 0})
    assert cfg.max_pages_per_chunk == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_pages_per_chunk": -1},
        {"max_chars_per_chunk": 0},
        {"max_chars_per_chunk": -100},
    ],
)
def test_summary_config_rejects_invalid_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        SummaryConfig.from_dict(kwargs)
