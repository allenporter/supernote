"""Configuration model for the Prometheus metrics component (`MetricsConfig`)."""

from __future__ import annotations

from dataclasses import dataclass

from mashumaro.mixins.json import DataClassJSONMixin

__all__ = ["MetricsConfig"]


@dataclass
class MetricsConfig(DataClassJSONMixin):
    """Per-component settings for `supernote.server.components.metrics`."""

    enabled: bool = True
    """Whether the Prometheus metrics endpoint and HTTP middleware are enabled."""

    path: str = "/metrics"
    """HTTP URL path where Prometheus metrics are exposed."""

    def __post_init__(self) -> None:
        if not self.path or not self.path.startswith("/"):
            raise ValueError(
                "metrics.path must be a non-empty URL path starting with '/'"
            )
