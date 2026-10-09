"""Background service for periodic automated recycle bin garbage collection."""

import asyncio
import logging
import time
from dataclasses import dataclass

from supernote.server.metrics import (
    RECYCLE_BIN_CLEANUP_BYTES_FREED_TOTAL,
    RECYCLE_BIN_CLEANUP_DURATION_SECONDS,
    RECYCLE_BIN_CLEANUP_ITEMS_PURGED_TOTAL,
    RECYCLE_BIN_CLEANUP_RUNS_TOTAL,
)
from supernote.server.services.file import FileService

logger = logging.getLogger(__name__)

__all__ = ["RecycleBinCleanupService", "RecycleCleanupStats"]


@dataclass
class RecycleCleanupStats:
    """Statistics for recycle bin cleanup operations."""

    purged_count: int = 0
    bytes_freed: int = 0

    def merge(self, other: "RecycleCleanupStats") -> None:
        """Merge stats from another cleanup operation."""
        self.purged_count += other.purged_count
        self.bytes_freed += other.bytes_freed


class RecycleBinCleanupService:
    """Service to periodically prune recycle bin entries older than retention window."""

    def __init__(
        self,
        file_service: FileService,
        retention_days: int = 30,
        interval_seconds: float = 86400.0,
        batch_size: int = 100,
    ) -> None:
        if retention_days < 0:
            raise ValueError(f"retention_days cannot be negative, got {retention_days}")
        if batch_size <= 0:
            raise ValueError(f"batch_size must be positive, got {batch_size}")
        if interval_seconds <= 0:
            raise ValueError(
                f"interval_seconds must be positive, got {interval_seconds}"
            )
        self.file_service = file_service
        self.retention_days = retention_days
        self.interval_seconds = interval_seconds
        self.batch_size = batch_size
        self._shutdown_event = asyncio.Event()
        self._polling_task: asyncio.Task[None] | None = None

    async def run_cleanup(
        self,
        retention_days: int | None = None,
        batch_size: int | None = None,
    ) -> RecycleCleanupStats:
        """Execute garbage collection sweep with bounded batching."""
        effective_days = (
            self.retention_days if retention_days is None else retention_days
        )
        effective_batch_size = self.batch_size if batch_size is None else batch_size

        if effective_days < 0:
            raise ValueError(f"retention_days cannot be negative, got {effective_days}")
        if effective_batch_size <= 0:
            raise ValueError(f"batch_size must be positive, got {effective_batch_size}")

        cutoff_ms = int((time.time() - (effective_days * 86400)) * 1000)
        start_time = time.perf_counter()
        stats = RecycleCleanupStats()

        try:
            while not self._shutdown_event.is_set():
                purged, freed = await self.file_service.purge_recycle(
                    older_than_ms=cutoff_ms,
                    limit=effective_batch_size,
                )
                stats.purged_count += purged
                stats.bytes_freed += freed

                if purged == 0 or purged < effective_batch_size:
                    break

                await asyncio.sleep(0)

            duration = time.perf_counter() - start_time
            RECYCLE_BIN_CLEANUP_RUNS_TOTAL.labels(status="success").inc()
            RECYCLE_BIN_CLEANUP_DURATION_SECONDS.observe(duration)
            RECYCLE_BIN_CLEANUP_ITEMS_PURGED_TOTAL.inc(stats.purged_count)
            RECYCLE_BIN_CLEANUP_BYTES_FREED_TOTAL.inc(stats.bytes_freed)

            logger.info(
                "Recycle bin cleanup completed: status=success, duration=%.4fs, purged_count=%d, bytes_freed=%d",
                duration,
                stats.purged_count,
                stats.bytes_freed,
                extra={
                    "status": "success",
                    "duration": duration,
                    "purged_count": stats.purged_count,
                    "bytes_freed": stats.bytes_freed,
                },
            )
            return stats

        except Exception as e:
            duration = time.perf_counter() - start_time
            RECYCLE_BIN_CLEANUP_RUNS_TOTAL.labels(status="failure").inc()
            RECYCLE_BIN_CLEANUP_DURATION_SECONDS.observe(duration)
            logger.error(
                "Recycle bin cleanup failed: status=failure, duration=%.4fs, error=%s",
                duration,
                e,
                extra={"status": "failure", "duration": duration, "error": str(e)},
                exc_info=True,
            )
            raise

    async def _poll_loop(self) -> None:
        """Background loop executing periodic cleanup runs on configured schedule."""
        logger.info("Starting background recycle bin cleanup polling loop...")
        while not self._shutdown_event.is_set():
            try:
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(), timeout=self.interval_seconds
                    )
                    break
                except asyncio.TimeoutError:
                    pass

                if self._shutdown_event.is_set():
                    break

                await self.run_cleanup()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "Error in recycle bin cleanup polling loop: %s",
                    e,
                    exc_info=True,
                )

    async def start(self) -> None:
        """Start the background cleanup service."""
        if self._polling_task is not None and not self._polling_task.done():
            logger.warning("RecycleBinCleanupService is already running.")
            return

        logger.info("Starting RecycleBinCleanupService...")
        self._shutdown_event.clear()
        self._polling_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Stop the background cleanup service."""
        logger.info("Stopping RecycleBinCleanupService...")
        self._shutdown_event.set()
        if self._polling_task is not None:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            finally:
                self._polling_task = None
