import asyncio
import logging
from typing import Set

from sqlalchemy import select

from ..db.models.note_processing import NotePageContentDO
from ..db.session import DatabaseSessionManager
from ..events import Event, LocalEventBus, NoteDeletedEvent, NoteUpdatedEvent
from ..services.file import FileService
from ..services.processor_modules import ProcessorModule
from ..services.summary import SummaryService

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
        self._shutdown_event = asyncio.Event()
        self.modules: list[ProcessorModule] = []

    def register_module(self, module: ProcessorModule) -> None:
        """Register a processing module."""
        self.modules.append(module)
        logger.info(f"Registered processor module: {module.name}")

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

    async def stop(self) -> None:
        """Stop the processor service."""
        logger.info("Stopping ProcessorService...")
        self._shutdown_event.set()

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
        logger.info(f"Received delete for note: {event.file_id}")
        # TODO: Implement cleanup logic (delete PNGs, OCR text, Vectors)
        pass

    async def recover_tasks(self) -> None:
        """Check DB for incomplete tasks on startup."""
        logger.info("Recovering pending processing tasks...")
        # TODO: Query SystemTaskDO for incomplete items
        # and re-enqueue associated file_ids
        pass

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

        # 1. Run Global Modules (e.g., PageHashing)
        for module in self.modules:
            try:
                if await module.should_process(
                    file_id, self.session_manager, page_index=None
                ):
                    logger.info(
                        f"Running global module {module.name} for file {file_id}"
                    )
                    await module.process(file_id, self.session_manager, page_index=None)
            except Exception as e:
                logger.error(
                    f"Global module {module.name} failed for file {file_id}: {e}",
                    exc_info=True,
                )

        # 2. Identify Pages
        # Query NotePageContentDO to see what pages exist (populated by HashingModule)
        async with self.session_manager.session() as session:
            stmt = (
                select(NotePageContentDO.page_index)
                .where(NotePageContentDO.file_id == file_id)
                .order_by(NotePageContentDO.page_index)
            )
            result = await session.execute(stmt)
            page_indices = result.scalars().all()

        if not page_indices:
            logger.info(f"No pages found for file {file_id}. Skipping page tasks.")

        # 3. Run Page-Level Modules
        for page_index in page_indices:
            for module in self.modules:
                try:
                    if await module.should_process(
                        file_id, self.session_manager, page_index=page_index
                    ):
                        logger.info(
                            f"Running module {module.name} for file {file_id} page {page_index}"
                        )
                        await module.process(
                            file_id,
                            self.session_manager,
                            page_index=page_index,
                        )
                except Exception as e:
                    logger.error(
                        f"Module {module.name} failed for file {file_id} page {page_index}: {e}",
                        exc_info=True,
                    )
