"""Prometheus metrics server component (`MetricsComponent`)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

from .storage import STORAGE_METRICS_COLLECTOR_KEY, StorageMetricsCollector

__all__ = [
    "STORAGE_METRICS_COLLECTOR_KEY",
    "MetricsComponent",
    "StorageMetricsCollector",
]


class MetricsComponent:
    """Vertical component managing Prometheus HTTP exposition and storage metrics collection."""

    domain = "metrics"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("http",)

    def __init__(self) -> None:
        self._collector: StorageMetricsCollector | None = None

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Instantiate `StorageMetricsCollector` and expose it via `STORAGE_METRICS_COLLECTOR_KEY`."""
        collector = StorageMetricsCollector(core.blob_storage)
        core.app[STORAGE_METRICS_COLLECTOR_KEY] = collector
        self._collector = collector

    async def async_start(self, core: ServerCore) -> None:
        """Start periodic blob storage inventory collection."""
        assert self._collector is not None
        await self._collector.start()

    async def async_stop(self, core: ServerCore) -> None:
        """Idempotently stop the background storage metrics collector."""
        collector = self._collector
        self._collector = None
        if collector is not None:
            await collector.stop()
