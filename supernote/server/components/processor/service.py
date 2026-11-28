"""Asynchronous `.note` processing pipeline orchestrator and recovery loop.

`ProcessorService` subscribes to `NoteUpdatedEvent`, `SyncCompletedEvent`, and
`VfsItemPurgedEvent` on `supernote.server.events.LocalEventBus` and runs registered
`supernote.server.components.processor.ProcessorModule` stages in DAG order:
1. Global Pre-Stages: `PageHashingModule` -> `NoteMetadataModule`
2. Per-Page Stages (parallel): `PngConversionModule` -> `OcrModule` -> `EmbeddingModule`
3. Global Post-Stage: `SummaryModule`

Includes startup recovery (`recover_tasks`), missing/version-outdated task discovery
(`recover_missing_tasks`), a 5-minute stalled-task polling loop, and publish of
`NoteProcessingCompletedEvent`. See `supernote.guides.note_processing_design` and
`supernote.guides.mcp`.
"""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Collection, Sequence
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import and_, case, delete, or_, select

from supernote.models.base import ProcessingStatus, TaskEntityType, TaskType
from supernote.models.extended import (
    SystemTaskVO,
)
from supernote.server.constants import (
    DEFAULT_PAGE_CONCURRENCY,
)
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    SystemTaskDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import (
    Event,
    LocalEventBus,
    NoteProcessingCompletedEvent,
    NoteProcessingFailedEvent,
    NoteUpdatedEvent,
    SyncCompletedEvent,
    VfsItemPurgedEvent,
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
from supernote.server.services.file import FileService
from supernote.server.utils.image import (
    DEFAULT_IMAGE_EXCLUDE_PATTERNS,
    is_indexable_image_path,
    is_processable_filename,
)

from .base import ProcessorModule, TaskGraph, TaskScope

logger = logging.getLogger(__name__)

_IMAGE_NAME_SUFFIX_PATTERNS: tuple[str, ...] = (
    "%.png",
    "%.jpg",
    "%.jpeg",
    "%.gif",
    "%.webp",
    "%.bmp",
)


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
        coordination_service: Any = None,
        concurrency: int = 2,
        page_concurrency: int = DEFAULT_PAGE_CONCURRENCY,
        *,
        enable_image_processing: bool = True,
        image_include_patterns: Sequence[str] = (),
        image_exclude_patterns: Sequence[str] = DEFAULT_IMAGE_EXCLUDE_PATTERNS,
    ) -> None:
        self.event_bus = event_bus
        self.session_manager = session_manager
        self.file_service = file_service
        self.coordination_service = coordination_service
        self.concurrency = concurrency
        self.page_concurrency = page_concurrency
        self.enable_image_processing = enable_image_processing
        self.image_include_patterns = tuple(image_include_patterns)
        self.image_exclude_patterns = tuple(image_exclude_patterns)

        self.queue: asyncio.Queue[tuple[int, int]] = (
            asyncio.Queue()
        )  # Queue of (user_id, file_id)
        self.processing_files: set[tuple[int, int]] = set()
        self._file_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._file_lock_refcounts: dict[tuple[int, int], int] = {}
        self.workers: list[asyncio.Task] = []
        self.polling_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._processing_enabled = asyncio.Event()
        init_note_processing_metrics()
        self._set_processing_enabled(True)
        self._update_queue_metrics()

        # Task DAG registry
        self.task_graph: TaskGraph = TaskGraph.empty()

    @property
    def page_modules(self) -> list[ProcessorModule]:
        """Page-scoped modules in deterministic topological order."""
        return [m for m in self.task_graph.modules if m.scope == TaskScope.PAGE]

    @property
    def global_post_modules(self) -> list[ProcessorModule]:
        """File-scoped modules that depend transitively on at least one page module."""
        return [
            m
            for m in self.task_graph.modules
            if m.scope == TaskScope.FILE
            and self.task_graph.has_page_ancestor(m.task_type)
        ]

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
    async def _file_lock(self, user_id: int, file_id: int) -> AsyncGenerator[None]:
        """Serialize processing and deletion per (user_id, file_id) without leaking idle locks."""
        lock_key = (user_id, file_id)
        lock = self._file_locks.setdefault(lock_key, asyncio.Lock())
        self._file_lock_refcounts[lock_key] = (
            self._file_lock_refcounts.get(lock_key, 0) + 1
        )
        try:
            async with lock:
                yield
        finally:
            remaining = self._file_lock_refcounts[lock_key] - 1
            if remaining <= 0:
                self._file_lock_refcounts.pop(lock_key, None)
                self._file_locks.pop(lock_key, None)
            else:
                self._file_lock_refcounts[lock_key] = remaining

    def set_modules(self, modules: Sequence[ProcessorModule]) -> None:
        """Validate and install the processor task dependency graph."""
        self.task_graph = TaskGraph.build(modules)
        init_processor_module_metrics(
            m.name
            for m in self.task_graph.modules
            if self.task_graph.is_effectively_enabled(m.task_type)
        )
        logger.info("Registered %d processor modules.", len(self.task_graph))

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
        self.event_bus.subscribe(VfsItemPurgedEvent, self.handle_vfs_item_purged)
        self.event_bus.subscribe(SyncCompletedEvent, self.handle_sync_completed)

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

    def _processable_name_filter(self) -> Any:
        """Return a SQLAlchemy predicate matching `.note` and (when enabled) standalone image filenames."""
        filters = [UserFileDO.file_name.ilike("%.note")]
        if self.enable_image_processing:
            filters.extend(
                UserFileDO.file_name.ilike(pattern)
                for pattern in _IMAGE_NAME_SUFFIX_PATTERNS
            )
        return or_(*filters)

    def _should_process_file_path(self, file_path: str) -> bool:
        """Return True when `file_path` is a `.note` file or an allowed standalone image."""
        if file_path.lower().endswith(".note"):
            return True
        return is_indexable_image_path(
            file_path,
            enabled=self.enable_image_processing,
            include_patterns=self.image_include_patterns,
            exclude_patterns=self.image_exclude_patterns,
        )

    async def handle_note_updated(self, event: Event) -> None:
        """Enqueue file for processing."""
        if not isinstance(event, NoteUpdatedEvent):
            return
        file_path = event.file_path
        if not file_path:
            file_path = await self.file_service.get_full_path_by_node(
                event.user_id, event.file_id
            )
        if not file_path or not self._should_process_file_path(file_path):
            logger.debug(
                f"Skipping missing, excluded, or disabled file {event.file_id} ({file_path})"
            )
            return
        if event.defer_processing:
            logger.debug(
                f"Deferring processing for note {event.file_id} ({file_path}) until sync completes"
            )
            async with self.session_manager.session() as session:
                await session.execute(
                    delete(SystemTaskDO).where(
                        SystemTaskDO.user_id == event.user_id,
                        SystemTaskDO.entity_type == TaskEntityType.FILE.value,
                        SystemTaskDO.entity_id == event.file_id,
                        SystemTaskDO.task_type == TaskType.PAGE_HASHING,
                    )
                )
                await session.commit()
            return
        logger.info(f"Received update for file: {event.file_id} ({file_path})")
        item = (event.user_id, event.file_id)
        if item not in self.processing_files:
            self.processing_files.add(item)
            await self.queue.put(item)
            self._update_queue_metrics()

    async def handle_sync_completed(self, event: Event) -> None:
        """Discover and enqueue unprocessed or updated .note files after sync completes."""
        if not isinstance(event, SyncCompletedEvent):
            return
        await self.recover_missing_tasks(user_id=event.user_id)

    async def handle_vfs_item_purged(self, event: Event) -> None:
        """Clean up artifacts when a processed file is permanently purged."""
        if not isinstance(event, VfsItemPurgedEvent):
            return
        if event.is_folder or not is_processable_filename(event.name):
            return
        file_id = event.item_id
        logger.info(f"Received delete for note: {file_id}")

        async with self._file_lock(event.user_id, file_id):
            for module in reversed(self.task_graph.modules):
                await module.cleanup_file(file_id, event.user_id, self.session_manager)

            async with self.session_manager.session() as session:
                await session.execute(
                    delete(NotePageContentDO).where(
                        NotePageContentDO.file_id == file_id
                    )
                )
                await session.execute(
                    delete(SystemTaskDO).where(
                        SystemTaskDO.user_id == event.user_id,
                        SystemTaskDO.entity_type == TaskEntityType.FILE.value,
                        SystemTaskDO.entity_id == file_id,
                    )
                )
                await session.commit()

        logger.info(f"Cleanup complete for deleted note: {file_id}")

    async def recover_tasks(self) -> None:
        """Check DB for incomplete tasks on startup."""
        logger.info("Recovering pending processing tasks...")
        async with self.session_manager.session() as session:
            # Find all (user_id, entity_id) pairs that have any file task NOT in COMPLETED status
            stmt = (
                select(SystemTaskDO.user_id, SystemTaskDO.entity_id)
                .where(
                    SystemTaskDO.entity_type == TaskEntityType.FILE.value,
                    SystemTaskDO.status != ProcessingStatus.COMPLETED,
                )
                .distinct()
            )
            result = await session.execute(stmt)
            targets = result.all()

        for uid, file_id in targets:
            logger.info(f"Recovering incomplete pipeline for user {uid} file {file_id}")
            item = (uid, file_id)
            if item not in self.processing_files:
                self.processing_files.add(item)
                await self.queue.put(item)
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
                select(SystemTaskDO.user_id, SystemTaskDO.entity_id)
                .where(SystemTaskDO.entity_type == TaskEntityType.FILE.value)
                .where(SystemTaskDO.status != ProcessingStatus.COMPLETED)
                .where(SystemTaskDO.update_time < stale_threshold_ms)
                .distinct()
            )
            result = await session.execute(stmt)
            targets = result.all()

        if not targets:
            return

        logger.info(f"Found {len(targets)} stalled files. Enqueuing...")
        PROCESSOR_STALLED_TASKS_RECOVERED_TOTAL.inc(len(targets))
        for uid, file_id in targets:
            item = (uid, file_id)
            if item not in self.processing_files:
                logger.info(f"Enqueuing stalled user {uid} file {file_id} for retry.")
                self.processing_files.add(item)
                await self.queue.put(item)
        self._update_queue_metrics()

    async def recover_missing_tasks(self, user_id: int | None = None) -> None:
        """Find .note files that have missing or outdated tasks and enqueue them."""
        logger.info("Checking for files with missing tasks...")
        any_task_exists = (
            select(SystemTaskDO.id)
            .where(
                SystemTaskDO.user_id == UserFileDO.user_id,
                SystemTaskDO.entity_type == TaskEntityType.FILE.value,
                SystemTaskDO.entity_id == UserFileDO.id,
            )
            .correlate(UserFileDO)
            .exists()
        )
        conditions = [~any_task_exists]

        for module in self.task_graph.modules:
            if not self.task_graph.is_effectively_enabled(module.task_type):
                continue
            if module.scope == TaskScope.FILE:
                task_exists = select(SystemTaskDO.id).where(
                    SystemTaskDO.user_id == UserFileDO.user_id,
                    SystemTaskDO.entity_type == TaskEntityType.FILE.value,
                    SystemTaskDO.entity_id == UserFileDO.id,
                    SystemTaskDO.task_type == module.task_type,
                    SystemTaskDO.key == "global",
                )
                if module.version is not None:
                    task_exists = task_exists.where(SystemTaskDO.data == module.version)
                missing_cond = ~task_exists.correlate(UserFileDO).exists()
                if not module.supports_standalone_images:
                    missing_cond = and_(
                        UserFileDO.file_name.ilike("%.note"),
                        missing_cond,
                    )
                conditions.append(missing_cond)
            else:
                page_task_exists = select(SystemTaskDO.id).where(
                    SystemTaskDO.user_id == UserFileDO.user_id,
                    SystemTaskDO.entity_type == TaskEntityType.FILE.value,
                    SystemTaskDO.entity_id == NotePageContentDO.file_id,
                    SystemTaskDO.task_type == module.task_type,
                    SystemTaskDO.key == "page_" + NotePageContentDO.page_id,
                )
                if module.version is not None:
                    page_task_exists = page_task_exists.where(
                        SystemTaskDO.data == module.version
                    )
                page_missing_exists = (
                    select(NotePageContentDO.id)
                    .where(
                        NotePageContentDO.file_id == UserFileDO.id,
                        NotePageContentDO.page_id != "",
                        ~page_task_exists.correlate(
                            UserFileDO, NotePageContentDO
                        ).exists(),
                    )
                    .correlate(UserFileDO)
                    .exists()
                )
                if not module.supports_standalone_images:
                    page_missing_exists = and_(
                        UserFileDO.file_name.ilike("%.note"),
                        page_missing_exists,
                    )
                conditions.append(page_missing_exists)

        async with self.session_manager.session() as session:
            stmt = (
                select(UserFileDO.id, UserFileDO.user_id, UserFileDO.file_name)
                .where(
                    self._processable_name_filter(),
                    UserFileDO.is_active == "Y",
                    UserFileDO.is_folder == "N",
                )
                .where(or_(*conditions))
            )
            if user_id is not None:
                stmt = stmt.where(UserFileDO.user_id == user_id)
            result = await session.execute(stmt)
            candidates = result.all()

        missing: list[tuple[int, int]] = []
        for file_id, uid, file_name in candidates:
            if not file_name.lower().endswith(".note"):
                full_path = await self.file_service.get_full_path_by_node(uid, file_id)
                if not self._should_process_file_path(full_path):
                    continue
            missing.append((file_id, uid))

        if not missing:
            return

        logger.info(f"Found {len(missing)} files with missing tasks. Enqueuing...")
        PROCESSOR_MISSING_TASKS_RECOVERED_TOTAL.inc(len(missing))
        for file_id, uid in missing:
            item = (uid, file_id)
            if item not in self.processing_files:
                logger.info(
                    f"Enqueuing user {uid} file {file_id} for initial processing."
                )
                self.processing_files.add(item)
                await self.queue.put(item)
        self._update_queue_metrics()

    async def worker_loop(self, worker_id: int) -> None:
        """Background worker to process items from the queue."""
        logger.debug(f"Worker {worker_id} started.")
        while not self._shutdown_event.is_set():
            try:
                # Wait until processing is enabled
                await self._processing_enabled.wait()

                item = await self.queue.get()
                user_id, file_id = item
                self._update_queue_metrics()

                # Re-check processing enabled status in case it was paused while we were waiting on get()
                if not self.is_processing_enabled():
                    await self.queue.put(item)
                    self.queue.task_done()
                    self._update_queue_metrics()
                    await asyncio.sleep(0.5)
                    continue
                try:
                    await self.process_file(file_id, user_id=user_id)
                except Exception as e:
                    logger.error(
                        f"Error processing user {user_id} file {file_id}: {e}",
                        exc_info=True,
                    )
                finally:
                    self.processing_files.discard(item)
                    self.queue.task_done()
                    self._update_queue_metrics()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} encountered error: {e}")

    async def process_file(
        self,
        file_id: int,
        *,
        user_id: int,
        task_types: Collection[str] | None = None,
        page_indices: set[int] | None = None,
    ) -> bool:
        """Orchestrate the processing pipeline (or a subset of task_types/page_indices) for a single file."""
        mode = (
            NoteProcessingMode.FULL
            if task_types is None and page_indices is None
            else NoteProcessingMode.ON_DEMAND
        )
        async with self._file_lock(user_id, file_id):
            with track_note_processing_run(mode=mode) as run:
                ok = await self._process_file_locked(
                    file_id,
                    user_id=user_id,
                    task_types=task_types,
                    page_indices=page_indices,
                )
                run.set_succeeded(ok)
                return ok

    def _collect_page_frontier(
        self,
        run_graph: TaskGraph,
        completed: set[str],
    ) -> list[ProcessorModule]:
        """Collect the maximal `PAGE` sub-DAG reachable before the next `FILE` barrier."""
        frontier: set[str] = set()
        result: list[ProcessorModule] = []
        for mod in run_graph.modules:
            if mod.scope != TaskScope.PAGE or mod.task_type in completed:
                continue
            if all(
                dep in completed or dep in frontier
                for dep in run_graph.depends_on(mod.task_type)
            ):
                frontier.add(mod.task_type)
                result.append(mod)
        return result

    async def _load_pages(
        self, file_id: int, page_indices: set[int] | None
    ) -> list[tuple[int, str]]:
        """Query ordered `(page_index, page_id)` pairs for ``file_id``."""
        async with self.session_manager.session() as session:
            stmt = (
                select(NotePageContentDO.page_index, NotePageContentDO.page_id)
                .where(NotePageContentDO.file_id == file_id)
                .order_by(NotePageContentDO.page_index)
            )
            if page_indices is not None:
                stmt = stmt.where(NotePageContentDO.page_index.in_(page_indices))
            result = await session.execute(stmt)
            return [(int(idx), str(pid)) for idx, pid in result.all() if pid]

    async def _process_file_locked(
        self,
        file_id: int,
        *,
        user_id: int,
        task_types: Collection[str] | None = None,
        page_indices: set[int] | None = None,
    ) -> bool:
        logger.info(f"Processing user {user_id} file {file_id}...")

        if not self.task_graph:
            logger.error("Modules not registered. Skipping processing.")
            return False

        if task_types is not None or page_indices is not None:
            requested = (
                task_types
                if task_types is not None
                else [m.task_type for m in self.task_graph.modules]
            )
            run_graph = self.task_graph.subset(
                requested,
                exclude_page_dependent_file_tasks=page_indices is not None,
            )
        else:
            run_graph = self.task_graph

        if not run_graph:
            return True

        completed: set[str] = set()
        task_succeeded: dict[str, bool] = {}
        overall_ok = True

        while len(completed) < len(run_graph):
            ready = [
                m
                for m in run_graph.modules
                if m.task_type not in completed
                and all(dep in completed for dep in run_graph.depends_on(m.task_type))
            ]
            ready_file = [m for m in ready if m.scope == TaskScope.FILE]

            if ready_file:
                for mod in ready_file:
                    task_type = mod.task_type
                    if any(
                        not task_succeeded.get(dep, False)
                        for dep in run_graph.depends_on(task_type)
                    ):
                        task_succeeded[task_type] = False
                        completed.add(task_type)
                        continue

                    if await mod.run(file_id, self.session_manager, user_id=user_id):
                        task_succeeded[task_type] = True
                    else:
                        logger.error(
                            f"File module {mod.name} failed for file {file_id}."
                        )
                        await self._publish_processing_failed(
                            file_id, mod.name, user_id=user_id
                        )
                        task_succeeded[task_type] = False
                        overall_ok = False
                    completed.add(task_type)
                continue

            ready_page = [m.task_type for m in ready if m.scope == TaskScope.PAGE]
            page_frontier = self._collect_page_frontier(run_graph, completed)
            frontier_types = {m.task_type for m in page_frontier}
            has_runnable_root = any(
                all(
                    task_succeeded.get(dep, False)
                    for dep in run_graph.depends_on(t)
                    if dep not in frontier_types
                )
                for t in ready_page
            )
            if not has_runnable_root:
                for mod in page_frontier:
                    task_succeeded[mod.task_type] = False
                    completed.add(mod.task_type)
                continue

            pages = await self._load_pages(file_id, page_indices)
            if not pages:
                logger.info(f"No pages found for file {file_id}. Skipping page tasks.")
                for mod in page_frontier:
                    task_succeeded[mod.task_type] = all(
                        task_succeeded.get(dep, False)
                        for dep in run_graph.depends_on(mod.task_type)
                    )
                    completed.add(mod.task_type)
                continue

            sem = asyncio.Semaphore(self.page_concurrency)

            async def throttled_process_page(
                page_index: int, page_id: str
            ) -> dict[str, bool]:
                async with sem:
                    return await self._process_page_dag(
                        file_id,
                        page_index,
                        page_id,
                        user_id=user_id,
                        run_graph=run_graph,
                        page_frontier=page_frontier,
                        external_succeeded=task_succeeded,
                    )

            page_results = await asyncio.gather(
                *(
                    throttled_process_page(page_index, page_id)
                    for page_index, page_id in pages
                )
            )

            for mod in page_frontier:
                t = mod.task_type
                all_pages_for_task_ok = all(r.get(t, False) for r in page_results)
                task_succeeded[t] = all_pages_for_task_ok
                if not all_pages_for_task_ok:
                    overall_ok = False
                completed.add(t)

        if (
            task_types is None
            and page_indices is None
            and (
                overall_ok
                or any(
                    task_succeeded.get(m.task_type, False)
                    for m in run_graph.modules
                    if m.scope == TaskScope.FILE
                    and not run_graph.has_page_ancestor(m.task_type)
                )
            )
        ):
            await self._publish_processing_completed(file_id, user_id=user_id)

        return overall_ok

    async def _publish_processing_completed(
        self, file_id: int, *, user_id: int
    ) -> None:
        """Publish NoteProcessingCompletedEvent after pipeline stages complete."""
        async with self.session_manager.session() as session:
            result = await session.execute(
                select(UserFileDO).where(
                    UserFileDO.id == file_id,
                    UserFileDO.user_id == user_id,
                )
            )
            user_file = result.scalar_one_or_none()
            if not isinstance(user_file, UserFileDO):
                return

        file_path = await self.file_service.get_full_path_by_node(user_id, file_id)
        await self.event_bus.publish(
            NoteProcessingCompletedEvent(
                file_id=file_id,
                user_id=user_id,
                file_path=file_path,
            )
        )

    async def _publish_processing_failed(
        self,
        file_id: int,
        module_name: str,
        *,
        user_id: int,
        page_id: str | None = None,
    ) -> None:
        """Publish NoteProcessingFailedEvent when a module fails."""
        async with self.session_manager.session() as session:
            result = await session.execute(
                select(UserFileDO).where(
                    UserFileDO.id == file_id,
                    UserFileDO.user_id == user_id,
                )
            )
            user_file = result.scalar_one_or_none()
            if not isinstance(user_file, UserFileDO):
                return
            key = f"page_{page_id}" if page_id else "global"
            task_err = await session.scalar(
                select(SystemTaskDO.last_error)
                .where(
                    SystemTaskDO.user_id == user_id,
                    SystemTaskDO.entity_type == TaskEntityType.FILE.value,
                    SystemTaskDO.entity_id == file_id,
                    SystemTaskDO.key == key,
                )
                .order_by(SystemTaskDO.update_time.desc())
            )

        file_path = await self.file_service.get_full_path_by_node(user_id, file_id)
        await self.event_bus.publish(
            NoteProcessingFailedEvent(
                file_id=file_id,
                user_id=user_id,
                file_path=file_path,
                module_name=module_name,
                error=task_err or f"{module_name} failed",
                page_id=page_id,
            )
        )

    async def _process_page_dag(
        self,
        file_id: int,
        page_index: int,
        page_id: str,
        *,
        user_id: int,
        run_graph: TaskGraph,
        page_frontier: Sequence[ProcessorModule],
        external_succeeded: dict[str, bool],
    ) -> dict[str, bool]:
        """Execute a `PAGE` sub-DAG for a single page, isolating failures to dependent branches."""
        frontier_types = {m.task_type for m in page_frontier}
        page_task_ok: dict[str, bool] = {}
        try:
            for module in page_frontier:
                task_type = module.task_type
                deps = run_graph.depends_on(task_type)
                if any(
                    not (
                        page_task_ok.get(dep, False)
                        if dep in frontier_types
                        else external_succeeded.get(dep, False)
                    )
                    for dep in deps
                ):
                    page_task_ok[task_type] = False
                    continue

                if await module.run(
                    file_id,
                    self.session_manager,
                    page_index=page_index,
                    page_id=page_id,
                    user_id=user_id,
                ):
                    page_task_ok[task_type] = True
                else:
                    logger.warning(
                        f"Page {page_id} (idx {page_index}) processing failed at {module.name} for file {file_id}"
                    )
                    await self._publish_processing_failed(
                        file_id, module.name, user_id=user_id, page_id=page_id
                    )
                    page_task_ok[task_type] = False
            return page_task_ok
        except Exception as e:
            logger.error(
                f"Unhandled error processing page {page_id} (idx {page_index}) for file {file_id}: {e}",
                exc_info=True,
            )
            return page_task_ok

    def resolve_task_type(self, name: str) -> str:
        """Resolve a built-in friendly/raw `TaskType` or registered `TaskGraph` stage name."""
        stripped = name.strip()
        if not stripped:
            raise ValueError(f"Invalid task_type: {name}")
        try:
            return TaskType.from_friendly(stripped).value
        except ValueError:
            pass

        resolved = self.task_graph.resolve_task_type(stripped)
        if resolved is not None:
            return resolved
        raise ValueError(f"Invalid task_type: {name}")

    async def reprocess_tasks(
        self,
        task_type: str,
        file_id: int | None = None,
        *,
        cascade: bool = False,
    ) -> list[int]:
        """Clear matching `SystemTaskDO` checkpoints and re-enqueue active target files."""
        stmt = delete(SystemTaskDO)

        if task_type.strip().upper() != "ALL":
            canonical_type = self.resolve_task_type(task_type)
            if cascade:
                types_to_clear = [
                    canonical_type,
                    *sorted(self.task_graph.descendants(canonical_type)),
                ]
            else:
                types_to_clear = [canonical_type]
            stmt = stmt.where(SystemTaskDO.task_type.in_(types_to_clear))

        async with self.session_manager.session() as session:
            if file_id is not None:
                file_stmt = select(UserFileDO.user_id, UserFileDO.file_name).where(
                    UserFileDO.id == file_id,
                    UserFileDO.is_active == "Y",
                )
                row = (await session.execute(file_stmt)).one_or_none()
                candidates = [(file_id, row[0], row[1])] if row is not None else []
            else:
                file_stmt = select(
                    UserFileDO.id, UserFileDO.user_id, UserFileDO.file_name
                ).where(
                    self._processable_name_filter(),
                    UserFileDO.is_active == "Y",
                    UserFileDO.is_folder == "N",
                )
                candidates = list((await session.execute(file_stmt)).all())

        targets: list[tuple[int, int, str]] = []
        for fid, uid, fname in candidates:
            if not fname.lower().endswith(".note"):
                fpath = await self.file_service.get_full_path_by_node(uid, fid)
                if not self._should_process_file_path(fpath):
                    continue
                targets.append((fid, uid, fpath))
            else:
                targets.append((fid, uid, fname))

        async with self.session_manager.session() as session:
            stmt = stmt.where(SystemTaskDO.entity_type == TaskEntityType.FILE.value)
            if file_id is not None:
                stmt = stmt.where(SystemTaskDO.entity_id == file_id)
                if targets:
                    stmt = stmt.where(SystemTaskDO.user_id == targets[0][1])
            await session.execute(stmt)
            await session.commit()

        for fid, uid, fpath in targets:
            await self.event_bus.publish(
                NoteUpdatedEvent(file_id=fid, user_id=uid, file_path=fpath)
            )
        return [fid for fid, _, _ in targets]

    async def list_system_tasks(
        self,
        user_id: int | None = None,
        limit: int = 100,
        status: str | None = None,
        file_id: int | None = None,
        task_type: str | None = None,
        *,
        entity_type: TaskEntityType | None = None,
    ) -> list[SystemTaskDO]:
        """List recent system tasks with optional filtering, prioritizing failed and active tasks."""
        status_priority = case(
            (SystemTaskDO.status == ProcessingStatus.FAILED, 0),
            (SystemTaskDO.status == ProcessingStatus.PROCESSING, 1),
            (SystemTaskDO.status == ProcessingStatus.PENDING, 2),
            else_=3,
        )
        async with self.session_manager.session() as session:
            stmt = select(SystemTaskDO)
            if user_id is not None:
                stmt = stmt.where(SystemTaskDO.user_id == user_id)
            if entity_type is not None:
                stmt = stmt.where(SystemTaskDO.entity_type == entity_type.value)
            if status:
                stmt = stmt.where(SystemTaskDO.status == status.upper())
            if file_id is not None:
                stmt = stmt.where(
                    SystemTaskDO.entity_type == TaskEntityType.FILE.value,
                    SystemTaskDO.entity_id == file_id,
                )
            if task_type:
                stmt = stmt.where(SystemTaskDO.task_type == task_type)
            stmt = stmt.order_by(
                status_priority.asc(), SystemTaskDO.update_time.desc()
            ).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def list_user_system_task_vos(
        self,
        user_id: int,
        limit: int = 100,
    ) -> tuple[list[SystemTaskVO], list[int]]:
        """Return enriched SystemTaskVOs (with file_name and page_index) and in-flight file IDs for user_id."""
        status_priority = case(
            (SystemTaskDO.status == ProcessingStatus.FAILED, 0),
            (SystemTaskDO.status == ProcessingStatus.PROCESSING, 1),
            (SystemTaskDO.status == ProcessingStatus.PENDING, 2),
            else_=3,
        )
        in_flight_candidates = [
            fid for uid, fid in self.processing_files if uid == user_id
        ]
        async with self.session_manager.session() as session:
            stmt = (
                select(
                    SystemTaskDO,
                    UserFileDO.file_name,
                    NotePageContentDO.page_index,
                )
                .join(
                    UserFileDO,
                    and_(
                        SystemTaskDO.entity_id == UserFileDO.id,
                        SystemTaskDO.user_id == UserFileDO.user_id,
                    ),
                )
                .outerjoin(
                    NotePageContentDO,
                    and_(
                        NotePageContentDO.file_id == SystemTaskDO.entity_id,
                        "page_" + NotePageContentDO.page_id == SystemTaskDO.key,
                    ),
                )
                .where(
                    SystemTaskDO.user_id == user_id,
                    SystemTaskDO.entity_type == TaskEntityType.FILE.value,
                    UserFileDO.is_active == "Y",
                )
                .order_by(status_priority.asc(), SystemTaskDO.update_time.desc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).all()

            user_in_flight: list[int] = []
            if in_flight_candidates:
                owned_in_flight = await session.execute(
                    select(UserFileDO.id).where(
                        UserFileDO.user_id == user_id,
                        UserFileDO.is_active == "Y",
                        UserFileDO.id.in_(in_flight_candidates),
                    )
                )
                user_in_flight = sorted(owned_in_flight.scalars().all())

        vos = [
            SystemTaskVO(
                id=task.id,
                file_id=task.entity_id,
                task_type=task.task_type,
                key=task.key,
                status=ProcessingStatus(task.status),
                retry_count=task.retry_count,
                last_error=task.last_error,
                update_time=task.update_time,
                file_name=file_name,
                page_index=page_index,
            )
            for task, file_name, page_index in rows
        ]
        return vos, user_in_flight

    async def retry_failed_tasks(
        self,
        user_id: int,
        file_id: int | None = None,
    ) -> list[int]:
        """Clear FAILED SystemTaskDO checkpoints for user_id (or a specific file_id) and re-enqueue."""
        async with self.session_manager.session() as session:
            failed_files_stmt = (
                select(UserFileDO.id)
                .join(
                    SystemTaskDO,
                    and_(
                        SystemTaskDO.entity_id == UserFileDO.id,
                        SystemTaskDO.user_id == UserFileDO.user_id,
                    ),
                )
                .where(
                    SystemTaskDO.user_id == user_id,
                    SystemTaskDO.entity_type == TaskEntityType.FILE.value,
                    UserFileDO.is_active == "Y",
                    SystemTaskDO.status == ProcessingStatus.FAILED,
                )
                .distinct()
            )
            if file_id is not None:
                failed_files_stmt = failed_files_stmt.where(UserFileDO.id == file_id)

            target_file_ids = sorted(
                (await session.execute(failed_files_stmt)).scalars().all()
            )
            if not target_file_ids:
                return []

            await session.execute(
                delete(SystemTaskDO).where(
                    SystemTaskDO.user_id == user_id,
                    SystemTaskDO.entity_type == TaskEntityType.FILE.value,
                    SystemTaskDO.entity_id.in_(target_file_ids),
                    or_(
                        SystemTaskDO.status == ProcessingStatus.FAILED,
                        and_(
                            SystemTaskDO.key == "global",
                            SystemTaskDO.task_type != TaskType.PAGE_HASHING.value,
                        ),
                    ),
                )
            )
            await session.commit()

        for fid in target_file_ids:
            await self.event_bus.publish(
                NoteUpdatedEvent(file_id=fid, user_id=user_id, file_path="")
            )
        return target_file_ids

    def _resolve_file_status(
        self, user_id: int, file_id: int, tasks: list[SystemTaskDO]
    ) -> ProcessingStatus:
        """Aggregate task rows and active queue membership into a single file status."""
        if (user_id, file_id) in self.processing_files:
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
                    select(SystemTaskDO).where(
                        SystemTaskDO.user_id == user_id,
                        SystemTaskDO.entity_type == TaskEntityType.FILE.value,
                        SystemTaskDO.entity_id.in_(owned_file_ids),
                    )
                )
                for task in task_rows.scalars().all():
                    tasks_by_file[task.entity_id].append(task)

        return {
            file_id: (
                self._resolve_file_status(user_id, file_id, tasks_by_file[file_id])
                if file_id in owned_file_ids
                else ProcessingStatus.NONE
            )
            for file_id in file_ids
        }
