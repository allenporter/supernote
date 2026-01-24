import asyncio
import logging
import time
from typing import List, Set

from sqlalchemy import delete, select

from supernote.models.base import ProcessingStatus

from ..constants import CACHE_BUCKET
from ..db.models.file import UserFileDO
from ..db.models.note_processing import NotePageContentDO, SystemTaskDO
from ..db.session import DatabaseSessionManager
from ..events import Event, LocalEventBus, NoteDeletedEvent, NoteUpdatedEvent
from ..services.file import FileService
from ..services.processor_modules import ProcessorModule
from ..services.summary import SummaryService
from ..utils.paths import get_page_png_path

logger = logging.getLogger(__name__)


class ProcessorService:
    """
    Manages the asynchronous processing pipeline for .note files.

    Responsibilities:
    1. Listens for NoteUpdatedEvents to enqueue processing tasks.
    2. Manages a background worker pool to process pages incrementally.
    3. Handles startup recovery of interrupted tasks.
    """

    def __init__(
        self,
        event_bus: LocalEventBus,
        session_manager: DatabaseSessionManager,
        file_service: FileService,
        summary_service: SummaryService,
        concurrency: int = 2,
    ) -> None:
        self.event_bus = event_bus
        self.session_manager = session_manager
        self.file_service = file_service
        self.summary_service = summary_service
        self.concurrency = concurrency

        self.queue: asyncio.Queue[int] = asyncio.Queue()  # Queue of file_ids
        self.processing_files: Set[int] = set()
        self.workers: list[asyncio.Task] = []
        self.polling_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()

        # Module registry
        self.global_pre_modules: List[ProcessorModule] = []
        self.page_modules: List[ProcessorModule] = []
        self.global_post_modules: List[ProcessorModule] = []

    def register_modules(
        self,
        hashing: ProcessorModule,
        png: ProcessorModule,
        ocr: ProcessorModule,
        embedding: ProcessorModule,
        summary: ProcessorModule,
    ) -> None:
        """Register processing modules in logical order."""
        self.global_pre_modules = [hashing]
        self.page_modules = [png, ocr, embedding]
        self.global_post_modules = [summary]
        logger.info("Registered all processor modules.")

    async def start(self) -> None:
        """Start the processor service workers and subscriptions."""
        logger.info("Starting ProcessorService...")

        # subscribe to events
        self.event_bus.subscribe(NoteUpdatedEvent, self.handle_note_updated)
        self.event_bus.subscribe(NoteDeletedEvent, self.handle_note_deleted)

        # Start workers
        for i in range(self.concurrency):
            worker = asyncio.create_task(self.worker_loop(i))
            self.workers.append(worker)

        # Recover pending tasks
        asyncio.create_task(self.recover_tasks())
        # Discover missing tasks
        asyncio.create_task(self.recover_missing_tasks())

        # Start Polling Loop
        self.polling_task = asyncio.create_task(self.poll_loop())

    async def stop(self) -> None:
        """Stop the processor service."""
        logger.info("Stopping ProcessorService...")
        self._shutdown_event.set()

        # Stop Polling
        if self.polling_task:
            self.polling_task.cancel()
            try:
                await self.polling_task
            except asyncio.CancelledError:
                pass

        # Cancel workers
        for worker in self.workers:
            worker.cancel()

        await asyncio.gather(*self.workers, return_exceptions=True)

    async def handle_note_updated(self, event: Event) -> None:
        """Enqueue file for processing."""
        if not isinstance(event, NoteUpdatedEvent):
            return
        logger.info(f"Received update for note: {event.file_id} ({event.file_path})")
        if event.file_id not in self.processing_files:
            self.processing_files.add(event.file_id)
            await self.queue.put(event.file_id)

    async def handle_note_deleted(self, event: Event) -> None:
        """Clean up artifacts for deleted note."""
        if not isinstance(event, NoteDeletedEvent):
            return
        file_id = event.file_id
        logger.info(f"Received delete for note: {file_id}")

        async with self.session_manager.session() as session:
            # Get all pages to know which PNGs to delete
            stmt = select(NotePageContentDO.page_id).where(
                NotePageContentDO.file_id == file_id
            )
            result = await session.execute(stmt)
            page_ids = result.scalars().all()

            # Delete DB records
            await session.execute(
                delete(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
            )
            await session.execute(
                delete(SystemTaskDO).where(SystemTaskDO.file_id == file_id)
            )
            await session.commit()

        # Delete Blobs (PNGs)
        for page_id in page_ids:
            if not page_id:
                continue
            png_path = get_page_png_path(file_id, page_id)
            try:
                await self.file_service.blob_storage.delete(CACHE_BUCKET, png_path)
            except Exception as e:
                logger.warning(
                    f"Failed to delete PNG for {file_id} page {page_id}: {e}"
                )

        logger.info(f"Cleanup complete for deleted note: {file_id}")

    async def recover_tasks(self) -> None:
        """Check DB for incomplete tasks on startup."""
        logger.info("Recovering pending processing tasks...")
        async with self.session_manager.session() as session:
            # Find all file_ids that have any task NOT in COMPLETED status
            stmt = (
                select(SystemTaskDO.file_id)
                .where(SystemTaskDO.status != ProcessingStatus.COMPLETED)
                .distinct()
            )
            result = await session.execute(stmt)
            file_ids = result.scalars().all()

        for file_id in file_ids:
            logger.info(f"Recovering incomplete pipeline for file {file_id}")
            if file_id not in self.processing_files:
                self.processing_files.add(file_id)
                await self.queue.put(file_id)

    async def poll_loop(self) -> None:
        """Background loop to poll for stalled tasks."""
        logger.info("Starting background task polling loop...")
        while not self._shutdown_event.is_set():
            try:
                # Wait for 5 minutes (adjustable)
                # We wait first to avoid thundering herd on startup (recover_tasks handles that)
                await asyncio.sleep(300)
                await self.recover_stalled_tasks()
                await self.recover_missing_tasks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in polling loop: {e}", exc_info=True)

    async def recover_stalled_tasks(self) -> None:
        """Find tasks that haven't been updated recently and retry them."""
        logger.info("Checking for stalled tasks...")
        # Stale threshold: 5 minutes ago
        stale_threshold_ms = int((time.time() - 300) * 1000)

        async with self.session_manager.session() as session:
            stmt = (
                select(SystemTaskDO.file_id)
                .where(SystemTaskDO.status != ProcessingStatus.COMPLETED)
                .where(SystemTaskDO.update_time < stale_threshold_ms)
                .distinct()
            )
            result = await session.execute(stmt)
            file_ids = result.scalars().all()

        if not file_ids:
            return

        logger.info(f"Found {len(file_ids)} stalled files. Enqueuing...")
        for file_id in file_ids:
            if file_id not in self.processing_files:
                logger.info(f"Enqueuing stalled file {file_id} for retry.")
                self.processing_files.add(file_id)
                await self.queue.put(file_id)

    async def recover_missing_tasks(self) -> None:
        """Find .note files that have no system tasks and enqueue them."""
        logger.info("Checking for files with missing tasks...")
        async with self.session_manager.session() as session:
            # Subquery to find file_ids that exist in f_system_task
            task_exists_stmt = select(SystemTaskDO.file_id)

            # Find all UserFileDO with .note extension that are NOT in f_system_task
            stmt = (
                select(UserFileDO.id, UserFileDO.user_id)
                .where(UserFileDO.file_name.like("%.note"))
                .where(UserFileDO.id.not_in(task_exists_stmt))
            )
            result = await session.execute(stmt)
            missing = result.all()

        if not missing:
            return

        logger.info(f"Found {len(missing)} files with missing tasks. Enqueuing...")
        for file_id, user_id in missing:
            if file_id not in self.processing_files:
                # We need the path for the event, but we can also just put it in the queue directly
                # if we change process_file to handle it. Actually process_file only needs file_id.
                # But handle_note_updated adds to self.processing_files.
                logger.info(f"Enqueuing file {file_id} for initial processing.")
                self.processing_files.add(file_id)
                await self.queue.put(file_id)

    async def worker_loop(self, worker_id: int) -> None:
        """Background worker to process items from the queue."""
        logger.debug(f"Worker {worker_id} started.")
        while not self._shutdown_event.is_set():
            try:
                file_id = await self.queue.get()
                try:
                    await self.process_file(file_id)
                except Exception as e:
                    logger.error(f"Error processing file {file_id}: {e}", exc_info=True)
                finally:
                    self.processing_files.discard(file_id)
                    self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} encountered error: {e}")

    async def process_file(self, file_id: int) -> None:
        """Orchestrate the processing pipeline for a single file."""
        logger.info(f"Processing file {file_id}...")

        if not self.global_pre_modules or not self.page_modules:
            logger.error("Modules not fully registered. Skipping processing.")
            return

        # Pipeline Stage: Global Pre-processing (Hashing)
        for module in self.global_pre_modules:
            if not await module.run(file_id, self.session_manager):
                logger.error(f"Pre-module {module.name} failed. Aborting pipeline.")
                return

        # Identify Pages
        async with self.session_manager.session() as session:
            # We want both index and ID. Index is needed for order, ID for tasks/storage.
            stmt = (
                select(NotePageContentDO.page_index, NotePageContentDO.page_id)
                .where(NotePageContentDO.file_id == file_id)
                .order_by(NotePageContentDO.page_index)
            )
            result = await session.execute(stmt)
            pages = result.all()  # List of (index, id) tuples

        if not pages:
            logger.info(f"No pages found for file {file_id}. Skipping page tasks.")
        else:
            # Pipeline Stage: Per-Page Processing (Parallel across pages)
            tasks = [
                self._process_page(file_id, page_index, page_id)
                for page_index, page_id in pages
                if page_id  # Strict Check: Everything must have a page_id
            ]
            await asyncio.gather(*tasks)

        # Pipeline Stage: Global Post-processing (Summary)
        for module in self.global_post_modules:
            await module.run(file_id, self.session_manager)

    async def _process_page(self, file_id: int, page_index: int, page_id: str) -> None:
        """Process all modules for a single page sequentially."""
        for module in self.page_modules:
            # We enforce page_id as the task key
            success = await module.run(
                file_id,
                self.session_manager,
                page_index=page_index,
                page_id=page_id,  # Pass page_id to modules
            )
            if not success:
                logger.warning(
                    f"Page {page_id} (idx {page_index}) processing stalled at {module.name} for file {file_id}"
                )
                break

    async def list_system_tasks(self, limit: int = 100) -> List[SystemTaskDO]:
        """List recent system tasks."""
        async with self.session_manager.session() as session:
            stmt = (
                select(SystemTaskDO)
                .order_by(SystemTaskDO.update_time.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())
