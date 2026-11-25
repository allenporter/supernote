"""Configuration model for the LLM Wiki server component (`WikiConfig`)."""

from __future__ import annotations

from dataclasses import dataclass

from mashumaro.mixins.json import DataClassJSONMixin

__all__ = ["WikiConfig"]


@dataclass
class WikiConfig(DataClassJSONMixin):
    """Per-component settings for `supernote.server.components.wiki`."""

    enabled: bool = False
    """Whether the wiki component is enabled."""

    auto_compile: bool = True
    """Whether background incremental compilation runs automatically on domain events."""

    debounce_seconds: float = 15.0
    """Per-user debounce window (seconds) coalescing multi-page sync bursts."""

    max_pages_per_batch: int = 5
    """Maximum wiki pages modified per single compilation turn."""

    daily_token_budget: int = 200_000
    """Per-user UTC daily LLM token cap across compile and lint passes."""

    lint_event_threshold: int = 10
    """Minimum compiled events before triggering a thresholded LLM semantic lint pass."""

    lint_interval_days: int = 7
    """Maximum days between thresholded LLM semantic lint passes when dirty."""

    def __post_init__(self) -> None:
        if self.debounce_seconds < 0:
            raise ValueError("debounce_seconds must be >= 0")
        if self.max_pages_per_batch < 1:
            raise ValueError("max_pages_per_batch must be >= 1")
        if self.daily_token_budget < 0:
            raise ValueError("daily_token_budget must be >= 0")
        if self.lint_event_threshold < 1:
            raise ValueError("lint_event_threshold must be >= 1")
        if self.lint_interval_days < 1:
            raise ValueError("lint_interval_days must be >= 1")
