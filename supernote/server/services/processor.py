"""Asynchronous 5-stage `.note` processing pipeline orchestrator and recovery loop.

`ProcessorService` subscribes to `NoteUpdatedEvent`, `SyncCompletedEvent`, and
`NoteDeletedEvent` on `supernote.server.events.LocalEventBus` and runs registered
`supernote.server.services.processor_modules.ProcessorModule` stages in order:
1. Global Pre-Stage: `PageHashingModule`
2. Per-Page Stage (parallel): `PngConversionModule` -> `OcrModule` -> `EmbeddingModule`
3. Global Post-Stage: `SummaryModule`

Includes startup recovery (`recover_tasks`), missing/version-outdated task discovery
(`recover_missing_tasks`), a 5-minute stalled-task polling loop, and publish of
`NoteProcessingCompletedEvent`. See `supernote.guides.note_processing_design` and
`supernote.guides.mcp`.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import delete, or_, select

from supernote.models.base import ProcessingStatus, TaskType
from supernote.models.extended import (
    NoteLinkVO,
    NotePageMetadataVO,
    NoteTitleVO,
    WebNoteMetadataVO,
)
from supernote.notebook import exceptions as notebook_exceptions
from supernote.notebook.fileformat import Notebook
from supernote.notebook.schema import (
    LinkDirection,
    LinkType,
    PageMetadata,
    SupernoteMetadata,
)
from supernote.server.metrics import (
    PROCESSOR_MISSING_TASKS_RECOVERED_TOTAL,
    PROCESSOR_QUEUE_PAUSED,
    PROCESSOR_QUEUE_SIZE,
    PROCESSOR_STALLED_TASKS_RECOVERED_TOTAL,
    NoteProcessingMode,
    init_note_processing_metrics,
    init_processor_module_metrics,
    track_note_processing_run,
)

from ..constants import DEFAULT_PAGE_CONCURRENCY
from ..db.models.file import UserFileDO
from ..db.models.note_processing import (
    NoteMetadataDO,
    NotePageContentDO,
    NotePageMetadataDO,
    SystemTaskDO,
)
from ..db.session import DatabaseSessionManager
from ..events import (
    BlobCleanupEvent,
    Event,
    LocalEventBus,
    NoteDeletedEvent,
    NoteProcessingCompletedEvent,
    NoteProcessingFailedEvent,
    NoteUpdatedEvent,
    SyncCompletedEvent,
)
from ..services.file import FileService
from ..services.processor_modules import ProcessorModule
from ..services.summary import SummaryService
from ..utils.note_content import infer_page_date, normalize_page_style_type

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
        coordination_service: Any = None,
        concurrency: int = 2,
        page_concurrency: int = DEFAULT_PAGE_CONCURRENCY,
    ) -> None:
        self.event_bus = event_bus
        self.session_manager = session_manager
        self.file_service = file_service
        self.summary_service = summary_service
        self.coordination_service = coordination_service
        self.concurrency = concurrency
        self.page_concurrency = page_concurrency

        self.queue: asyncio.Queue[int] = asyncio.Queue()  # Queue of file_ids
        self.processing_files: set[int] = set()
        self._file_locks: dict[int, asyncio.Lock] = {}
        self._file_lock_refcounts: dict[int, int] = {}
        self.workers: list[asyncio.Task] = []
        self.polling_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._processing_enabled = asyncio.Event()
        init_note_processing_metrics()
        self._set_processing_enabled(True)
        self._update_queue_metrics()

        # Module registry
        self.global_pre_modules: list[ProcessorModule] = []
        self.page_modules: list[ProcessorModule] = []
        self.global_post_modules: list[ProcessorModule] = []

    def _set_processing_enabled(self, enabled: bool) -> None:
        if enabled:
            self._processing_enabled.set()
            PROCESSOR_QUEUE_PAUSED.set(0)
        else:
            self._processing_enabled.clear()
            PROCESSOR_QUEUE_PAUSED.set(1)

    def _update_queue_metrics(self) -> None:
        PROCESSOR_QUEUE_SIZE.set(self.queue.qsize())

    @asynccontextmanager
    async def _file_lock(self, file_id: int) -> AsyncGenerator[None]:
        """Serialize processing and deletion per file_id without leaking idle locks."""
        lock = self._file_locks.setdefault(file_id, asyncio.Lock())
        self._file_lock_refcounts[file_id] = (
            self._file_lock_refcounts.get(file_id, 0) + 1
        )
        try:
            async with lock:
                yield
        finally:
            remaining = self._file_lock_refcounts[file_id] - 1
            if remaining <= 0:
                self._file_lock_refcounts.pop(file_id, None)
                self._file_locks.pop(file_id, None)
            else:
                self._file_lock_refcounts[file_id] = remaining

    def register_modules(
        self,
        hashing: ProcessorModule,
        png: ProcessorModule | None = None,
        ocr: ProcessorModule | None = None,
        embedding: ProcessorModule | None = None,
        summary: ProcessorModule | None = None,
    ) -> None:
        """Register processing modules in logical order."""
        self.global_pre_modules = [hashing]
        self.page_modules = [m for m in (png, ocr, embedding) if m is not None]
        self.global_post_modules = [m for m in (summary,) if m is not None]
        init_processor_module_metrics(
            m.name
            for m in (
                *self.global_pre_modules,
                *self.page_modules,
                *self.global_post_modules,
            )
            if m.enabled
        )
        logger.info("Registered all processor modules.")

    async def start(self) -> None:
        """Start the processor service workers and subscriptions."""
        logger.info("Starting ProcessorService...")

        # Load paused state from coordination service if available
        if self.coordination_service:
            try:
                paused_val = await self.coordination_service.get_value("queue_paused")
                if paused_val == "true":
                    self._set_processing_enabled(False)
                    logger.info(
                        "ProcessorService queue processing starts in PAUSED state."
                    )
                else:
                    self._set_processing_enabled(True)
            except Exception as e:
                logger.error(f"Failed to load queue paused state: {e}")
                self._set_processing_enabled(True)
        else:
            self._set_processing_enabled(True)

        # subscribe to events
        self.event_bus.subscribe(NoteUpdatedEvent, self.handle_note_updated)
        self.event_bus.subscribe(NoteDeletedEvent, self.handle_note_deleted)
        self.event_bus.subscribe(SyncCompletedEvent, self.handle_sync_completed)
        self.event_bus.subscribe(BlobCleanupEvent, self.handle_blob_cleanup)

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

    async def pause(self) -> None:
        """Pause processing of tasks."""
        self._set_processing_enabled(False)
        if self.coordination_service:
            try:
                await self.coordination_service.set_value("queue_paused", "true")
            except Exception as e:
                logger.error(f"Failed to persist queue paused state: {e}")
        logger.info("ProcessorService queue processing paused.")

    async def resume(self) -> None:
        """Resume processing of tasks."""
        self._set_processing_enabled(True)
        if self.coordination_service:
            try:
                await self.coordination_service.set_value("queue_paused", "false")
            except Exception as e:
                logger.error(f"Failed to persist queue resumed state: {e}")
        logger.info("ProcessorService queue processing resumed.")

        # Trigger immediate recovery scan on resume to pick up any pending work immediately
        asyncio.create_task(self.recover_tasks())
        asyncio.create_task(self.recover_missing_tasks())

    def is_processing_enabled(self) -> bool:
        """Check if queue processing is enabled."""
        return self._processing_enabled.is_set()

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
        if event.defer_processing:
            logger.debug(
                f"Deferring processing for note {event.file_id} ({event.file_path}) until sync completes"
            )
            async with self.session_manager.session() as session:
                await session.execute(
                    delete(SystemTaskDO).where(
                        SystemTaskDO.file_id == event.file_id,
                        SystemTaskDO.task_type == TaskType.PAGE_HASHING,
                    )
                )
                await session.commit()
            return
        logger.info(f"Received update for note: {event.file_id} ({event.file_path})")
        if event.file_id not in self.processing_files:
            self.processing_files.add(event.file_id)
            await self.queue.put(event.file_id)
            self._update_queue_metrics()

    async def handle_sync_completed(self, event: Event) -> None:
        """Discover and enqueue unprocessed or updated .note files after sync completes."""
        if not isinstance(event, SyncCompletedEvent):
            return
        await self.recover_missing_tasks(user_id=event.user_id)

    async def handle_note_deleted(self, event: Event) -> None:
        """Clean up artifacts for deleted note."""
        if not isinstance(event, NoteDeletedEvent):
            return
        file_id = event.file_id
        logger.info(f"Received delete for note: {file_id}")

        async with self._file_lock(file_id):
            for module in (
                *self.global_pre_modules,
                *self.page_modules,
                *self.global_post_modules,
            ):
                await module.cleanup_file(file_id, event.user_id, self.session_manager)

            async with self.session_manager.session() as session:
                await session.execute(
                    delete(NotePageContentDO).where(
                        NotePageContentDO.file_id == file_id
                    )
                )
                await session.execute(
                    delete(SystemTaskDO).where(SystemTaskDO.file_id == file_id)
                )
                await session.commit()

        logger.info(f"Cleanup complete for deleted note: {file_id}")

    async def handle_blob_cleanup(self, event: Event) -> None:
        """Clean up unreferenced user data blobs asynchronously."""
        if not isinstance(event, BlobCleanupEvent):
            return
        await self.file_service.cleanup_unreferenced_blobs(event.storage_keys)

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
        self._update_queue_metrics()

    async def poll_loop(self) -> None:
        """Background loop to poll for stalled tasks."""
        logger.info("Starting background task polling loop...")
        while not self._shutdown_event.is_set():
            try:
                # Wait for 5 minutes (adjustable)
                # We wait first to avoid thundering herd on startup (recover_tasks handles that)
                await asyncio.sleep(300)
                if self.is_processing_enabled():
                    await self.recover_stalled_tasks()
                    await self.recover_missing_tasks()
                    await self.summary_service.purge_expired_summaries()
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
        PROCESSOR_STALLED_TASKS_RECOVERED_TOTAL.inc(len(file_ids))
        for file_id in file_ids:
            if file_id not in self.processing_files:
                logger.info(f"Enqueuing stalled file {file_id} for retry.")
                self.processing_files.add(file_id)
                await self.queue.put(file_id)
        self._update_queue_metrics()

    async def recover_missing_tasks(self, user_id: int | None = None) -> None:
        """Find .note files that have missing or outdated tasks and enqueue them."""
        logger.info("Checking for files with missing tasks...")
        conditions = [UserFileDO.id.not_in(select(SystemTaskDO.file_id))]

        for module in (*self.global_pre_modules, *self.global_post_modules):
            if not module.enabled:
                continue
            task_stmt = (
                select(SystemTaskDO.file_id)
                .where(SystemTaskDO.task_type == module.task_type)
                .where(SystemTaskDO.key == "global")
            )
            if module.version is not None:
                task_stmt = task_stmt.where(SystemTaskDO.data == module.version)
            conditions.append(UserFileDO.id.not_in(task_stmt))

        for module in self.page_modules:
            if not module.enabled:
                continue
            page_task_exists = (
                select(SystemTaskDO.id)
                .where(SystemTaskDO.file_id == NotePageContentDO.file_id)
                .where(SystemTaskDO.task_type == module.task_type)
                .where(SystemTaskDO.key == "page_" + NotePageContentDO.page_id)
            )
            if module.version is not None:
                page_task_exists = page_task_exists.where(
                    SystemTaskDO.data == module.version
                )
            page_missing_stmt = (
                select(NotePageContentDO.file_id)
                .where(NotePageContentDO.page_id != "")
                .where(~page_task_exists.correlate(NotePageContentDO).exists())
            )
            conditions.append(UserFileDO.id.in_(page_missing_stmt))

        async with self.session_manager.session() as session:
            stmt = (
                select(UserFileDO.id, UserFileDO.user_id)
                .where(
                    UserFileDO.file_name.like("%.note"),
                    UserFileDO.is_active == "Y",
                )
                .where(or_(*conditions))
            )
            if user_id is not None:
                stmt = stmt.where(UserFileDO.user_id == user_id)
            result = await session.execute(stmt)
            missing = result.all()

        if not missing:
            return

        logger.info(f"Found {len(missing)} files with missing tasks. Enqueuing...")
        PROCESSOR_MISSING_TASKS_RECOVERED_TOTAL.inc(len(missing))
        for file_id, user_id in missing:
            if file_id not in self.processing_files:
                # We need the path for the event, but we can also just put it in the queue directly
                # if we change process_file to handle it. Actually process_file only needs file_id.
                # But handle_note_updated adds to self.processing_files.
                logger.info(f"Enqueuing file {file_id} for initial processing.")
                self.processing_files.add(file_id)
                await self.queue.put(file_id)
        self._update_queue_metrics()

    async def worker_loop(self, worker_id: int) -> None:
        """Background worker to process items from the queue."""
        logger.debug(f"Worker {worker_id} started.")
        while not self._shutdown_event.is_set():
            try:
                # Wait until processing is enabled
                await self._processing_enabled.wait()

                file_id = await self.queue.get()
                self._update_queue_metrics()

                # Re-check processing enabled status in case it was paused while we were waiting on get()
                if not self.is_processing_enabled():
                    await self.queue.put(file_id)
                    self.queue.task_done()
                    self._update_queue_metrics()
                    await asyncio.sleep(0.5)
                    continue
                try:
                    await self.process_file(file_id)
                except Exception as e:
                    logger.error(f"Error processing file {file_id}: {e}", exc_info=True)
                finally:
                    self.processing_files.discard(file_id)
                    self.queue.task_done()
                    self._update_queue_metrics()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} encountered error: {e}")

    async def process_file(
        self,
        file_id: int,
        task_types: set[TaskType] | None = None,
        page_indices: set[int] | None = None,
    ) -> bool:
        """Orchestrate the processing pipeline (or a subset of task_types/page_indices) for a single file."""
        mode = (
            NoteProcessingMode.FULL
            if task_types is None and page_indices is None
            else NoteProcessingMode.ON_DEMAND
        )
        async with self._file_lock(file_id):
            with track_note_processing_run(mode=mode) as run:
                ok = await self._process_file_locked(
                    file_id,
                    task_types=task_types,
                    page_indices=page_indices,
                )
                run.set_succeeded(ok)
                return ok

    async def _process_file_locked(
        self,
        file_id: int,
        task_types: set[TaskType] | None = None,
        page_indices: set[int] | None = None,
    ) -> bool:
        logger.info(f"Processing file {file_id}...")

        if not self.global_pre_modules:
            logger.error("Modules not fully registered. Skipping processing.")
            return False

        pre_modules = [
            m
            for m in self.global_pre_modules
            if task_types is None or m.task_type in task_types
        ]
        page_modules = [
            m
            for m in self.page_modules
            if task_types is None or m.task_type in task_types
        ]
        post_modules = [
            m
            for m in self.global_post_modules
            if (task_types is None or m.task_type in task_types)
            and page_indices is None
        ]

        # Pipeline Stage: Global Pre-processing (Hashing)
        for module in pre_modules:
            if not await module.run(file_id, self.session_manager):
                logger.error(f"Pre-module {module.name} failed. Aborting pipeline.")
                await self._publish_processing_failed(file_id, module.name)
                return False

        all_pages_ok = True
        if page_modules:
            # Identify Pages
            async with self.session_manager.session() as session:
                # We want both index and ID. Index is needed for order, ID for tasks/storage.
                stmt = (
                    select(NotePageContentDO.page_index, NotePageContentDO.page_id)
                    .where(NotePageContentDO.file_id == file_id)
                    .order_by(NotePageContentDO.page_index)
                )
                if page_indices is not None:
                    stmt = stmt.where(NotePageContentDO.page_index.in_(page_indices))
                result = await session.execute(stmt)
                pages = result.all()  # List of (index, id) tuples

            if not pages:
                logger.info(f"No pages found for file {file_id}. Skipping page tasks.")
            else:
                # Pipeline Stage: Per-Page Processing (Parallel across pages with limit)
                sem = asyncio.Semaphore(self.page_concurrency)

                async def throttled_process_page(page_index: int, page_id: str) -> bool:
                    async with sem:
                        return await self._process_page(
                            file_id, page_index, page_id, modules=page_modules
                        )

                tasks = [
                    throttled_process_page(page_index, page_id)
                    for page_index, page_id in pages
                    if page_id  # Strict Check: Everything must have a page_id
                ]
                page_results = await asyncio.gather(*tasks)
                all_pages_ok = all(page_results)

        # Pipeline Stage: Global Post-processing (Summary)
        post_ok = True
        for module in post_modules:
            if not await module.run(file_id, self.session_manager):
                await self._publish_processing_failed(file_id, module.name)
                post_ok = False

        if task_types is None and page_indices is None:
            await self._publish_processing_completed(file_id)

        return all_pages_ok and post_ok

    async def _publish_processing_completed(self, file_id: int) -> None:
        """Publish NoteProcessingCompletedEvent after pipeline stages complete."""
        async with self.session_manager.session() as session:
            result = await session.execute(
                select(UserFileDO).where(UserFileDO.id == file_id)
            )
            user_file = result.scalar_one_or_none()
            if not isinstance(user_file, UserFileDO):
                return

        file_path = await self.file_service.get_full_path_by_node(
            user_file.user_id, file_id
        )
        await self.event_bus.publish(
            NoteProcessingCompletedEvent(
                file_id=file_id,
                user_id=user_file.user_id,
                file_path=file_path,
            )
        )

    async def _publish_processing_failed(
        self, file_id: int, module_name: str, page_id: str | None = None
    ) -> None:
        """Publish NoteProcessingFailedEvent when a module fails."""
        async with self.session_manager.session() as session:
            result = await session.execute(
                select(UserFileDO).where(UserFileDO.id == file_id)
            )
            user_file = result.scalar_one_or_none()
            if not isinstance(user_file, UserFileDO):
                return
            key = f"page_{page_id}" if page_id else "global"
            task_err = await session.scalar(
                select(SystemTaskDO.last_error)
                .where(
                    SystemTaskDO.file_id == file_id,
                    SystemTaskDO.key == key,
                )
                .order_by(SystemTaskDO.update_time.desc())
            )

        file_path = await self.file_service.get_full_path_by_node(
            user_file.user_id, file_id
        )
        await self.event_bus.publish(
            NoteProcessingFailedEvent(
                file_id=file_id,
                user_id=user_file.user_id,
                file_path=file_path,
                module_name=module_name,
                error=task_err or f"{module_name} failed",
                page_id=page_id,
            )
        )

    async def _process_page(
        self,
        file_id: int,
        page_index: int,
        page_id: str,
        modules: list[ProcessorModule] | None = None,
    ) -> bool:
        """Process modules for a single page sequentially."""
        active_modules = modules if modules is not None else self.page_modules
        try:
            for module in active_modules:
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
                    await self._publish_processing_failed(
                        file_id, module.name, page_id=page_id
                    )
                    return False
            return True
        except Exception as e:
            logger.error(
                f"Unhandled error processing page {page_id} (idx {page_index}) for file {file_id}: {e}",
                exc_info=True,
            )
            return False

    async def list_system_tasks(
        self,
        user_id: int | None = None,
        limit: int = 100,
        status: str | None = None,
        file_id: int | None = None,
        task_type: str | None = None,
    ) -> list[SystemTaskDO]:
        """List recent system tasks with optional filtering."""
        async with self.session_manager.session() as session:
            stmt = select(SystemTaskDO)
            if user_id is not None:
                stmt = stmt.join(
                    UserFileDO, SystemTaskDO.file_id == UserFileDO.id
                ).where(UserFileDO.user_id == user_id)
            if status:
                stmt = stmt.where(SystemTaskDO.status == status.upper())
            if file_id is not None:
                stmt = stmt.where(SystemTaskDO.file_id == file_id)
            if task_type:
                stmt = stmt.where(SystemTaskDO.task_type == task_type)
            stmt = stmt.order_by(SystemTaskDO.update_time.desc()).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    def _resolve_file_status(
        self, file_id: int, tasks: list[SystemTaskDO]
    ) -> ProcessingStatus:
        """Aggregate task rows and active queue membership into a single file status."""
        if file_id in self.processing_files:
            if any(t.status == ProcessingStatus.PROCESSING for t in tasks):
                return ProcessingStatus.PROCESSING
            return ProcessingStatus.PENDING
        if not tasks:
            return ProcessingStatus.NONE
        if any(t.status == ProcessingStatus.FAILED for t in tasks):
            return ProcessingStatus.FAILED
        if any(t.status == ProcessingStatus.PROCESSING for t in tasks):
            return ProcessingStatus.PROCESSING
        if all(t.status == ProcessingStatus.COMPLETED for t in tasks):
            return ProcessingStatus.COMPLETED
        return ProcessingStatus.PENDING

    async def get_file_processing_statuses(
        self,
        user_id: int,
        file_ids: list[int],
    ) -> dict[int, ProcessingStatus]:
        """Return aggregated processing status for each requested file owned by user_id."""
        if not file_ids:
            return {}

        async with self.session_manager.session() as session:
            owned_rows = await session.execute(
                select(UserFileDO.id).where(
                    UserFileDO.user_id == user_id,
                    UserFileDO.id.in_(file_ids),
                )
            )
            owned_file_ids = set(owned_rows.scalars().all())

            tasks_by_file: dict[int, list[SystemTaskDO]] = {
                fid: [] for fid in owned_file_ids
            }
            if owned_file_ids:
                task_rows = await session.execute(
                    select(SystemTaskDO).where(SystemTaskDO.file_id.in_(owned_file_ids))
                )
                for task in task_rows.scalars().all():
                    tasks_by_file[task.file_id].append(task)

        return {
            file_id: (
                self._resolve_file_status(file_id, tasks_by_file[file_id])
                if file_id in owned_file_ids
                else ProcessingStatus.NONE
            )
            for file_id in file_ids
        }

    async def get_note_metadata(
        self,
        user_id: int,
        file_id: int,
    ) -> WebNoteMetadataVO | None:
        """Return structured notebook and per-page metadata for an active .note file owned by user_id."""
        async with self.session_manager.session() as session:
            file_row = (
                await session.execute(
                    select(UserFileDO).where(
                        UserFileDO.id == file_id,
                        UserFileDO.user_id == user_id,
                        UserFileDO.is_active == "Y",
                    )
                )
            ).scalar_one_or_none()
            if file_row is None:
                return None

            meta_do = await session.get(NoteMetadataDO, (user_id, file_id))
            if meta_do is None:
                return None

            page_rows = list(
                (
                    await session.execute(
                        select(NotePageMetadataDO)
                        .where(
                            NotePageMetadataDO.user_id == user_id,
                            NotePageMetadataDO.file_id == file_id,
                        )
                        .order_by(NotePageMetadataDO.page_index)
                    )
                )
                .scalars()
                .all()
            )

            header_dict = json.loads(meta_do.header_json)
            footer_dict = json.loads(meta_do.footer_json)
            if not isinstance(header_dict, dict) or not isinstance(footer_dict, dict):
                raise ValueError("header_json and footer_json must be JSON objects")
            notebook = Notebook(
                SupernoteMetadata(
                    type=meta_do.file_type or "note",
                    signature=meta_do.signature or "",
                    header=header_dict,
                    footer=footer_dict,
                    pages=[],
                )
            )

            outgoing_links = [
                lk for lk in notebook.links if lk.direction == LinkDirection.OUT
            ]
            external_native_ids = {
                lk.file_id
                for lk in outgoing_links
                if lk.file_id and lk.file_id != meta_do.native_file_id
            }
            native_to_file_id: dict[str, int] = {}
            if external_native_ids:
                ext_file_rows = (
                    await session.execute(
                        select(NoteMetadataDO.native_file_id, NoteMetadataDO.file_id)
                        .join(
                            UserFileDO,
                            (UserFileDO.id == NoteMetadataDO.file_id)
                            & (UserFileDO.user_id == NoteMetadataDO.user_id),
                        )
                        .where(
                            NoteMetadataDO.user_id == user_id,
                            NoteMetadataDO.native_file_id.in_(external_native_ids),
                            UserFileDO.is_active == "Y",
                        )
                    )
                ).all()
                for native_id, resolved_fid in ext_file_rows:
                    if native_id:
                        native_to_file_id[native_id] = resolved_fid

            page_index_by_target: dict[tuple[int, str], int] = {
                (file_id, pm.page_id): pm.page_index for pm in page_rows if pm.page_id
            }
            external_page_ids = {
                lk.page_id
                for lk in outgoing_links
                if lk.page_id and lk.file_id and lk.file_id in native_to_file_id
            }
            if external_page_ids and native_to_file_id:
                ext_page_rows = (
                    await session.execute(
                        select(
                            NotePageMetadataDO.file_id,
                            NotePageMetadataDO.page_id,
                            NotePageMetadataDO.page_index,
                        ).where(
                            NotePageMetadataDO.user_id == user_id,
                            NotePageMetadataDO.file_id.in_(native_to_file_id.values()),
                            NotePageMetadataDO.page_id.in_(external_page_ids),
                        )
                    )
                ).all()
                for ext_fid, ext_pid, ext_idx in ext_page_rows:
                    page_index_by_target[(ext_fid, ext_pid)] = ext_idx

        page_vos: list[NotePageMetadataVO] = []
        for pm in page_rows:
            has_five_star = False
            try:
                raw_page = json.loads(pm.page_json)
                if isinstance(raw_page, dict):
                    has_five_star = bool(PageMetadata.from_params(raw_page).five_star)
            except (
                json.JSONDecodeError,
                ValueError,
                TypeError,
                notebook_exceptions.ParserException,
            ) as err:
                logger.warning(
                    f"Failed to deserialize page_json for file {file_id} page {pm.page_index}: {err}"
                )

            inferred_dt = infer_page_date(pm.page_id)
            page_vos.append(
                NotePageMetadataVO(
                    page_index=pm.page_index,
                    page_id=pm.page_id,
                    date=inferred_dt.strftime("%Y-%m-%d") if inferred_dt else None,
                    style=normalize_page_style_type(pm.page_style),
                    is_blank=not pm.has_drawables,
                    has_five_star=has_five_star,
                    keywords=pm.keyword_texts,
                )
            )

        keywords_by_text: dict[str, list[int]] = {}
        for kw in notebook.keywords:
            if kw.keyword and kw.keyword.strip():
                text = kw.keyword.strip()
                indices = keywords_by_text.setdefault(text, [])
                if kw.page_number not in indices:
                    indices.append(kw.page_number)

        link_vos: list[NoteLinkVO] = []
        for lk in outgoing_links:
            link_type_name = (
                lk.link_type.name.lower()
                if isinstance(lk.link_type, LinkType)
                else str(lk.link_type)
            )
            if not lk.file_id or lk.file_id == meta_do.native_file_id:
                resolved_file_id: int | None = file_id if lk.page_id else None
            else:
                resolved_file_id = native_to_file_id.get(lk.file_id)

            target_page_index: int | None = None
            if lk.page_id and resolved_file_id is not None:
                target_page_index = page_index_by_target.get(
                    (resolved_file_id, lk.page_id)
                )
            if (
                target_page_index is None
                and lk.metadata.obj_page
                and lk.metadata.obj_page > 0
            ):
                target_page_index = lk.metadata.obj_page - 1

            link_vos.append(
                NoteLinkVO(
                    page_index=lk.page_number,
                    link_type=link_type_name,
                    target=lk.target,
                    target_file_id=(
                        resolved_file_id if resolved_file_id != file_id else None
                    ),
                    target_page_index=target_page_index,
                )
            )

        equipment = (
            str(notebook.metadata.header.apply_equipment)
            if notebook.metadata.header.apply_equipment
            else None
        )
        return WebNoteMetadataVO(
            file_id=file_id,
            equipment=equipment,
            total_pages=meta_do.total_pages,
            keywords=keywords_by_text,
            titles=[
                NoteTitleVO(
                    page_index=t.page_number,
                    level=t.heading_level,
                )
                for t in notebook.titles
            ],
            links=link_vos,
            pages=page_vos,
        )
