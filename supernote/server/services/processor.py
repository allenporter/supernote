import asyncio
import logging
import time
from typing import Any

from sqlalchemy import delete, or_, select

from supernote.models.base import ProcessingStatus, TaskType
from supernote.server.metrics import (
    PROCESSOR_FILES_PROCESSING,
    PROCESSOR_MISSING_TASKS_RECOVERED_TOTAL,
    PROCESSOR_QUEUE_SIZE,
    PROCESSOR_STALLED_TASKS_RECOVERED_TOTAL,
)

from ..constants import CACHE_BUCKET, DEFAULT_PAGE_CONCURRENCY
from ..db.models.file import UserFileDO
from ..db.models.note_processing import (
    NotePageContentDO,
    NoteTaskSyncDO,
    SystemTaskDO,
)
from ..db.models.schedule import ScheduleTaskDO
from ..db.models.summary import SummaryDO
from ..db.session import DatabaseSessionManager
from ..events import (
    BlobCleanupEvent,
    Event,
    LocalEventBus,
    NoteDeletedEvent,
    NoteProcessingCompletedEvent,
    NoteUpdatedEvent,
    ScheduleUpdatedEvent,
    SyncCompletedEvent,
)
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
        self.workers: list[asyncio.Task] = []
        self.polling_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._processing_enabled = asyncio.Event()
        self._processing_enabled.set()

        # Module registry
        self.global_pre_modules: list[ProcessorModule] = []
        self.page_modules: list[ProcessorModule] = []
        self.global_post_modules: list[ProcessorModule] = []

    def _update_queue_metrics(self) -> None:
        PROCESSOR_QUEUE_SIZE.set(self.queue.qsize())
        PROCESSOR_FILES_PROCESSING.set(len(self.processing_files))

    def register_modules(
        self,
        hashing: ProcessorModule,
        png: ProcessorModule | None = None,
        ocr: ProcessorModule | None = None,
        embedding: ProcessorModule | None = None,
        summary: ProcessorModule | None = None,
        task_extraction: ProcessorModule | None = None,
    ) -> None:
        """Register processing modules in logical order."""
        self.global_pre_modules = [hashing]
        self.page_modules = [m for m in (png, ocr, embedding) if m is not None]
        self.global_post_modules = [
            m for m in (summary, task_extraction) if m is not None
        ]
        logger.info("Registered all processor modules.")

    async def start(self) -> None:
        """Start the processor service workers and subscriptions."""
        logger.info("Starting ProcessorService...")

        # Load paused state from coordination service if available
        if self.coordination_service:
            try:
                paused_val = await self.coordination_service.get_value("queue_paused")
                if paused_val == "true":
                    self._processing_enabled.clear()
                    logger.info(
                        "ProcessorService queue processing starts in PAUSED state."
                    )
                else:
                    self._processing_enabled.set()
            except Exception as e:
                logger.error(f"Failed to load queue paused state: {e}")
                self._processing_enabled.set()
        else:
            self._processing_enabled.set()

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
        self._processing_enabled.clear()
        if self.coordination_service:
            try:
                await self.coordination_service.set_value("queue_paused", "true")
            except Exception as e:
                logger.error(f"Failed to persist queue paused state: {e}")
        logger.info("ProcessorService queue processing paused.")

    async def resume(self) -> None:
        """Resume processing of tasks."""
        self._processing_enabled.set()
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

        async with self.session_manager.session() as session:
            # Get all pages to know which PNGs to delete
            stmt = select(NotePageContentDO.page_id).where(
                NotePageContentDO.file_id == file_id
            )
            result = await session.execute(stmt)
            page_ids = result.scalars().all()

            # Collect parent group UUIDs and any handwriting blob keys attached to
            # the note's summaries or their now-empty parent summary groups so
            # unreferenced blobs can be cleaned up after the SummaryDO rows are deleted.
            summary_rows_stmt = select(
                SummaryDO.parent_unique_identifier,
                SummaryDO.handwrite_inner_name,
            ).where(SummaryDO.file_id == file_id)
            summary_rows = (await session.execute(summary_rows_stmt)).all()
            parent_uuids = {u for u, _ in summary_rows if u}
            candidate_blob_keys = {k for _, k in summary_rows if k}

            await session.execute(
                delete(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
            )
            await session.execute(
                delete(SystemTaskDO).where(SystemTaskDO.file_id == file_id)
            )
            # Clean up any open schedule tasks extracted from this notebook
            active_task_rows = (
                await session.execute(
                    select(
                        NoteTaskSyncDO.user_id,
                        NoteTaskSyncDO.schedule_task_id,
                    ).where(
                        NoteTaskSyncDO.file_id == file_id,
                        NoteTaskSyncDO.sync_status == "ACTIVE",
                        NoteTaskSyncDO.schedule_task_id.is_not(None),
                    )
                )
            ).all()
            schedule_users_to_notify: set[int] = set()
            if active_task_rows:
                task_ids_to_delete = [
                    tid for _, tid in active_task_rows if tid is not None
                ]
                if task_ids_to_delete:
                    del_res = await session.execute(
                        delete(ScheduleTaskDO).where(
                            ScheduleTaskDO.task_id.in_(task_ids_to_delete),
                            ScheduleTaskDO.status == "needsAction",
                        )
                    )
                    if getattr(del_res, "rowcount", 0) > 0:
                        schedule_users_to_notify = {uid for uid, _ in active_task_rows}
            await session.execute(
                delete(NoteTaskSyncDO).where(NoteTaskSyncDO.file_id == file_id)
            )
            await session.execute(delete(SummaryDO).where(SummaryDO.file_id == file_id))
            if parent_uuids:
                surviving_parent_stmt = (
                    select(SummaryDO.parent_unique_identifier)
                    .where(SummaryDO.parent_unique_identifier.in_(parent_uuids))
                    .group_by(SummaryDO.parent_unique_identifier)
                )
                surviving_parents = {
                    u
                    for u in (await session.execute(surviving_parent_stmt))
                    .scalars()
                    .all()
                    if u
                }
                empty_parent_uuids = parent_uuids - surviving_parents
                if empty_parent_uuids:
                    group_blobs_stmt = select(SummaryDO.handwrite_inner_name).where(
                        SummaryDO.unique_identifier.in_(empty_parent_uuids),
                        SummaryDO.is_summary_group.is_(True),
                        SummaryDO.handwrite_inner_name.is_not(None),
                    )
                    candidate_blob_keys.update(
                        k
                        for k in (await session.execute(group_blobs_stmt))
                        .scalars()
                        .all()
                        if k
                    )
                    await session.execute(
                        delete(SummaryDO).where(
                            SummaryDO.unique_identifier.in_(empty_parent_uuids),
                            SummaryDO.is_summary_group.is_(True),
                        )
                    )
            await session.commit()

        for notify_uid in schedule_users_to_notify:
            await self.event_bus.publish(ScheduleUpdatedEvent(user_id=notify_uid))

        await self.file_service.cleanup_unreferenced_blobs(candidate_blob_keys)

        # Delete Blobs (PNGs)
        for page_id in page_ids:
            if not page_id:
                continue
            png_path = get_page_png_path(file_id, page_id)
            try:
                await self.file_service.blob_storage.delete(CACHE_BUCKET, png_path)
            except (FileNotFoundError, OSError) as e:
                logger.warning(
                    f"Failed to delete PNG for {file_id} page {page_id}: {e}"
                )

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
    ) -> bool:
        """Orchestrate the processing pipeline (or a subset of task_types) for a single file."""
        lock = self._file_locks.setdefault(file_id, asyncio.Lock())
        async with lock:
            return await self._process_file_locked(file_id, task_types=task_types)

    async def _process_file_locked(
        self,
        file_id: int,
        task_types: set[TaskType] | None = None,
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
            if task_types is None or m.task_type in task_types
        ]

        # Pipeline Stage: Global Pre-processing (Hashing)
        for module in pre_modules:
            if not await module.run(file_id, self.session_manager):
                logger.error(f"Pre-module {module.name} failed. Aborting pipeline.")
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
                post_ok = False

        if task_types is None:
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
