"""Tests for `supernote.server.components.wiki.config`."""

from __future__ import annotations

import pytest

from supernote.server.components.wiki.config import WikiConfig


def test_wiki_config_defaults() -> None:
    cfg = WikiConfig.from_dict({})
    assert cfg.enabled is False
    assert cfg.auto_compile is True
    assert cfg.debounce_seconds == 15.0
    assert cfg.max_pages_per_batch == 5
    assert cfg.max_source_pages_per_turn == 8
    assert cfg.daily_token_budget == 200_000
    assert cfg.lint_event_threshold == 10
    assert cfg.lint_interval_days == 7


@pytest.mark.parametrize(
    "kwargs",
    [
        {"debounce_seconds": -1.0},
        {"max_pages_per_batch": 0},
        {"max_source_pages_per_turn": 0},
        {"daily_token_budget": -1},
        {"lint_event_threshold": 0},
        {"lint_interval_days": 0},
    ],
)
def test_wiki_config_rejects_invalid_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        WikiConfig.from_dict(kwargs)
