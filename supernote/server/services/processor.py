import asyncio
import logging
from typing import Set

from sqlalchemy import select

from ..db.models.note_processing import NotePageContentDO
from ..db.session import DatabaseSessionManager
from ..events import Event, LocalEventBus, NoteDeletedEvent, NoteUpdatedEvent
from ..services.file import FileService
from ..services.processor_modules.gemini_embedding import GeminiEmbeddingModule
from ..services.processor_modules.gemini_ocr import GeminiOcrModule
from ..services.processor_modules.page_hashing import PageHashingModule
from ..services.processor_modules.png_conversion import PngConversionModule
from ..services.processor_modules.summary import SummaryModule
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

        # Explicit modules
        self.hashing_module: PageHashingModule | None = None
        self.png_module: PngConversionModule | None = None
        self.ocr_module: GeminiOcrModule | None = None
        self.embedding_module: GeminiEmbeddingModule | None = None
        self.summary_module: SummaryModule | None = None

    def register_modules(
        self,
        hashing: PageHashingModule,
        png: PngConversionModule,
        ocr: GeminiOcrModule,
        embedding: GeminiEmbeddingModule,
        summary: SummaryModule,
    ) -> None:
        """Register processing modules."""
        self.hashing_module = hashing
        self.png_module = png
        self.ocr_module = ocr
        self.embedding_module = embedding
        self.summary_module = summary
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

        if not all(
            [
                self.hashing_module,
                self.png_module,
                self.ocr_module,
                self.embedding_module,
                self.summary_module,
            ]
        ):
            logger.error("Modules not fully registered. Skipping processing.")
            return

        # 1. Hashing (Global)
        # Detect changes. If no changes, return early?
        # For now, hashing just updates the DB state.
        if await self.hashing_module.run_if_needed(file_id, self.session_manager):  # type: ignore
            await self.hashing_module.process(file_id, self.session_manager)  # type: ignore

        # 2. Identify Pages
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

        # 3. Per-Page Pipeline (Explicit Order)
        for page_index in page_indices:
            # PNG acts as a gate for OCR
            if await self.png_module.run_if_needed(  # type: ignore
                file_id, self.session_manager, page_index=page_index
            ):
                await self.png_module.process(  # type: ignore
                    file_id, self.session_manager, page_index=page_index
                )

            # OCR acts as a gate for Embedding
            if await self.ocr_module.run_if_needed(  # type: ignore
                file_id, self.session_manager, page_index=page_index
            ):
                await self.ocr_module.process(  # type: ignore
                    file_id, self.session_manager, page_index=page_index
                )

            # Embedding
            if await self.embedding_module.run_if_needed(  # type: ignore
                file_id, self.session_manager, page_index=page_index
            ):
                await self.embedding_module.process(  # type: ignore
                    file_id, self.session_manager, page_index=page_index
                )

        # 4. Summary (Global)
        if await self.summary_module.run_if_needed(file_id, self.session_manager):  # type: ignore
            await self.summary_module.process(file_id, self.session_manager)  # type: ignore
