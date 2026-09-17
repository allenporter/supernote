import asyncio
import logging
import time

from ..metrics import (
    RECYCLE_BIN_CLEANUP_DURATION_SECONDS,
    RECYCLE_BIN_CLEANUP_ITEMS_PURGED_TOTAL,
    RECYCLE_BIN_CLEANUP_RUNS_TOTAL,
)
from .file import FileService

logger = logging.getLogger(__name__)


class RecycleBinCleanupService:
    """Periodically purges recycle bin entries older than a retention window.

    Mirrors the `ProcessorService.poll_loop` background-task pattern: a single
    asyncio task started on server startup, cancelled on shutdown, that sleeps
    for `interval_seconds` between runs.
    """

    def __init__(
        self,
        file_service: FileService,
        retention_days: int,
        interval_seconds: int,
        enabled: bool = True,
    ) -> None:
        self.file_service = file_service
        self.retention_days = retention_days
        self.interval_seconds = interval_seconds
        self.enabled = enabled
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background cleanup loop, if enabled."""
        if not self.enabled:
            logger.info(
                "Recycle bin cleanup job disabled "
                "(SUPERNOTE_RECYCLE_BIN_CLEANUP_ENABLED=false)."
            )
            return
        logger.info(
            "Starting recycle bin cleanup job "
            f"(retention_days={self.retention_days}, "
            f"interval_seconds={self.interval_seconds})."
        )
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Stop the background cleanup loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _poll_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.interval_seconds)
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in recycle bin cleanup loop: {e}", exc_info=True)

    async def run_once(self) -> int:
        """Run a single cleanup pass. Returns the number of files purged."""
        start_time = time.monotonic()
        try:
            purged_count = await self.file_service.purge_expired_recycle_entries(
                self.retention_days
            )
        except Exception:
            RECYCLE_BIN_CLEANUP_RUNS_TOTAL.labels(status="failure").inc()
            raise
        finally:
            RECYCLE_BIN_CLEANUP_DURATION_SECONDS.observe(time.monotonic() - start_time)

        RECYCLE_BIN_CLEANUP_RUNS_TOTAL.labels(status="success").inc()
        if purged_count:
            RECYCLE_BIN_CLEANUP_ITEMS_PURGED_TOTAL.inc(purged_count)
            logger.info(f"Recycle bin cleanup purged {purged_count} file(s).")
        else:
            logger.debug("Recycle bin cleanup found nothing to purge.")

        return purged_count
