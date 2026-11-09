"""Periodic background collector for blob storage and cache inventory metrics."""

from __future__ import annotations

import asyncio
import logging

from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.metrics import BlobStorageKind, set_blob_storage_metrics
from supernote.server.services.blob import BlobStorage

__all__ = [
    "DEFAULT_STORAGE_METRICS_INTERVAL_SECONDS",
    "StorageMetricsCollector",
]

logger = logging.getLogger(__name__)

DEFAULT_STORAGE_METRICS_INTERVAL_SECONDS = 300.0


class StorageMetricsCollector:
    """Periodically scans blob storage buckets and updates Prometheus gauges."""

    def __init__(
        self,
        blob_storage: BlobStorage,
        interval_seconds: float = DEFAULT_STORAGE_METRICS_INTERVAL_SECONDS,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.blob_storage = blob_storage
        self.interval_seconds = interval_seconds
        self._shutdown_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def collect_once(self) -> None:
        """Scan `USER_DATA_BUCKET` and `CACHE_BUCKET` once and set inventory gauges."""
        user_entries = await self.blob_storage.list_blob_sizes(USER_DATA_BUCKET)
        cache_entries = await self.blob_storage.list_blob_sizes(CACHE_BUCKET)

        png_objects = 0
        png_bytes = 0
        pdf_objects = 0
        pdf_bytes = 0
        for key, size in cache_entries:
            lower_key = key.lower()
            if lower_key.endswith(".png"):
                png_objects += 1
                png_bytes += size
            elif lower_key.endswith(".pdf"):
                pdf_objects += 1
                pdf_bytes += size

        set_blob_storage_metrics(
            counts={
                (USER_DATA_BUCKET, BlobStorageKind.USER_BLOB): (
                    len(user_entries),
                    sum(size for _, size in user_entries),
                ),
                (CACHE_BUCKET, BlobStorageKind.PNG): (png_objects, png_bytes),
                (CACHE_BUCKET, BlobStorageKind.PDF): (pdf_objects, pdf_bytes),
            },
            available_bytes=self.blob_storage.get_available_bytes(),
        )

    async def start(self) -> None:
        """Spawn the background timer task if not already running."""
        if self._task is not None and not self._task.done():
            return
        self._shutdown_event.clear()
        self._task = asyncio.create_task(
            self._run_loop(),
            name="storage-metrics-collector",
        )

    async def stop(self) -> None:
        """Stop the background timer task and wait for it to exit cleanly."""
        self._shutdown_event.set()
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                await self.collect_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unexpected error collecting blob storage metrics")

            try:
                async with asyncio.timeout(self.interval_seconds):
                    await self._shutdown_event.wait()
            except TimeoutError:
                continue
