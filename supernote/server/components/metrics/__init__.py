"""Prometheus metrics server component (`MetricsComponent`)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aiohttp import web

from supernote.server.core import ServerCore

from .config import MetricsConfig
from .storage import STORAGE_METRICS_COLLECTOR_KEY, StorageMetricsCollector

__all__ = [
    "METRICS_CONFIG_KEY",
    "STORAGE_METRICS_COLLECTOR_KEY",
    "MetricsComponent",
    "MetricsConfig",
    "StorageMetricsCollector",
]

METRICS_CONFIG_KEY: web.AppKey[MetricsConfig] = web.AppKey("metrics_config")


class MetricsComponent:
    """Vertical component managing Prometheus HTTP exposition and storage metrics collection."""

    domain = "metrics"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("http",)

    def __init__(self) -> None:
        self._collector: StorageMetricsCollector | None = None

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Parse `MetricsConfig`, instantiate `StorageMetricsCollector`, and register on `core.app`."""
        core.app[METRICS_CONFIG_KEY] = MetricsConfig.from_dict(dict(config))
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
