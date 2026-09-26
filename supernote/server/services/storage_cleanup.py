"""Background service for periodic cleanup of orphaned staging files and abandoned chunks."""

import asyncio
import logging

from prometheus_client import Counter

from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.metrics import (
    STORAGE_CLEANUP_BYTES_RECLAIMED_TOTAL,
    STORAGE_CLEANUP_CHUNKS_REMOVED_TOTAL,
    STORAGE_CLEANUP_TEMP_FILES_REMOVED_TOTAL,
)

from .blob import BlobStorage, CleanupStats

logger = logging.getLogger(__name__)

__all__ = ["StorageCleanupService"]


class StorageCleanupService:
    """Service to periodically prune orphaned storage temp staging files and abandoned upload chunks."""

    def __init__(
        self,
        blob_storage: BlobStorage,
        interval_seconds: float = 3600.0,
        temp_ttl_seconds: float = 86400.0,
        buckets: tuple[str, ...] = (USER_DATA_BUCKET,),
    ) -> None:
        """Initialize the storage cleanup service."""
        self.blob_storage = blob_storage
        self.interval_seconds = interval_seconds
        self.temp_ttl_seconds = temp_ttl_seconds
        self.buckets = buckets
        self._shutdown_event = asyncio.Event()
        self._polling_task: asyncio.Task[None] | None = None

    @staticmethod
    def _record_cleanup_metrics(
        label: str,
        stats: CleanupStats,
        counter: Counter,
    ) -> None:
        """Record metrics and log information for completed cleanup operations."""
        if stats.files_removed <= 0:
            return

        counter.inc(stats.files_removed)
        STORAGE_CLEANUP_BYTES_RECLAIMED_TOTAL.inc(stats.bytes_reclaimed)
        unit = "chunk(s)" if label.lower() == "chunk" else "file(s)"
        logger.info(
            "%s cleanup removed %d %s reclaiming %d byte(s).",
            label,
            stats.files_removed,
            unit,
            stats.bytes_reclaimed,
        )

    async def run_staging_cleanup(
        self, ttl_seconds: float | None = None
    ) -> CleanupStats:
        """Remove orphaned staging files older than ttl_seconds."""
        ttl = self.temp_ttl_seconds if ttl_seconds is None else ttl_seconds
        stats = await self.blob_storage.cleanup_staging(ttl)
        self._record_cleanup_metrics(
            "Staging", stats, STORAGE_CLEANUP_TEMP_FILES_REMOVED_TOTAL
        )
        return stats

    async def run_chunks_cleanup(
        self,
        ttl_seconds: float | None = None,
        bucket: str | None = None,
    ) -> CleanupStats:
        """Remove abandoned upload chunks older than ttl_seconds across configured buckets."""
        ttl = self.temp_ttl_seconds if ttl_seconds is None else ttl_seconds
        target_buckets = (bucket,) if bucket is not None else self.buckets
        total_stats = CleanupStats()
        for target_bucket in target_buckets:
            stats = await self.blob_storage.cleanup_chunks(target_bucket, ttl)
            total_stats.merge(stats)
        self._record_cleanup_metrics(
            "Chunk", total_stats, STORAGE_CLEANUP_CHUNKS_REMOVED_TOTAL
        )
        return total_stats

    async def run_cleanup(self) -> CleanupStats:
        """Execute a full cleanup cycle for both staging temp files and chunks."""
        total_stats = CleanupStats()
        staging_stats = await self.run_staging_cleanup()
        total_stats.merge(staging_stats)

        chunk_stats = await self.run_chunks_cleanup()
        total_stats.merge(chunk_stats)

        return total_stats

    async def _poll_loop(self) -> None:
        """Background loop executing periodic cleanup runs."""
        logger.info("Starting background storage cleanup polling loop...")
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(self.interval_seconds)
                if self._shutdown_event.is_set():
                    break
                await self.run_cleanup()
            except asyncio.CancelledError:
                break
            except OSError as e:
                logger.error(
                    "Filesystem error in storage cleanup polling loop: %s",
                    e,
                    exc_info=True,
                )

    async def start(self) -> None:
        """Start the cleanup service, performing an immediate startup sweep of staging files."""
        if self._polling_task is not None and not self._polling_task.done():
            logger.warning("StorageCleanupService is already running.")
            return

        logger.info("Starting StorageCleanupService...")
        self._shutdown_event.clear()

        # Immediate startup sweep for crash-orphaned staging temp files
        try:
            await self.run_staging_cleanup(ttl_seconds=0)
        except asyncio.CancelledError:
            raise
        except OSError as e:
            logger.error(
                "Filesystem error during startup staging cleanup sweep: %s",
                e,
                exc_info=True,
            )

        if self._shutdown_event.is_set():
            logger.warning(
                "StorageCleanupService was stopped during startup sweep; aborting poll loop."
            )
            return

        self._polling_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Stop the cleanup service and terminate background tasks."""
        logger.info("Stopping StorageCleanupService...")
        self._shutdown_event.set()
        if self._polling_task is not None:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            finally:
                self._polling_task = None
