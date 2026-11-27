"""Base `ProcessorModule` state-machine abstraction and pipeline stages.

Each `ProcessorModule` implements a single idempotent stage of the background `.note`
processing pipeline orchestrated by `supernote.server.components.processor.service.ProcessorService`
and checkpointed in `supernote.server.db.models.note_processing.SystemTaskDO`:

- `supernote.server.components.processor.page_hashing.PageHashingModule` (`TaskType.PAGE_HASHING`)
- `supernote.server.components.note_metadata.processor.NoteMetadataModule` (`TaskType.NOTE_METADATA`)
- `supernote.server.components.conversion.processor.PngConversionModule` (`TaskType.PNG_CONVERSION`)
- `supernote.server.components.transcript.processor.OcrModule` (`TaskType.OCR_EXTRACTION`)
- `supernote.server.components.search.processor.EmbeddingModule` (`TaskType.EMBEDDING_GENERATION`)
- `supernote.server.components.summary.processor.SummaryModule` (`TaskType.SUMMARY_GENERATION`)

See `supernote.guides.note_processing_design` and `supernote.guides.mcp`.
"""

from __future__ import annotations

import abc
import asyncio
import graphlib
import heapq
import logging
import time
from collections.abc import Iterable, Sequence
from enum import Enum

from supernote.models.base import ProcessingStatus
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.metrics import (
    PROCESSOR_TASK_DURATION_SECONDS,
    PROCESSOR_TASKS_TOTAL,
)
from supernote.server.utils.tasks import get_task, update_task_status

__all__ = [
    "DuplicateTaskError",
    "MissingTaskDependencyError",
    "ProcessorModule",
    "TaskDependencyCycleError",
    "TaskGraph",
    "TaskGraphError",
    "TaskScope",
]

logger = logging.getLogger(__name__)


def _task_key(task_type: str | Enum) -> str:
    """Return the wire/DB string value for a `TaskType` enum or raw task type string."""
    return str(task_type.value) if isinstance(task_type, Enum) else str(task_type)


class TaskScope(str, Enum):
    """Execution granularity for a `ProcessorModule`."""

    FILE = "file"
    """Runs once per file using checkpoint key ``'global'``."""

    PAGE = "page"
    """Fans out once per page using checkpoint key ``'page_{page_id}'``."""


class TaskGraphError(Exception):
    """Base exception for invalid processor task dependency graphs."""


class DuplicateTaskError(TaskGraphError):
    """Raised when two registered modules share the same `task_type`."""

    def __init__(self, task_type: str) -> None:
        self.task_type = task_type
        super().__init__(f"Processor task type {task_type!r} is already registered")


class MissingTaskDependencyError(TaskGraphError):
    """Raised when a module declares an unregistered `depends_on` task type."""

    def __init__(self, task_type: str, dependency: str) -> None:
        self.task_type = task_type
        self.dependency = dependency
        super().__init__(
            f"Processor task {task_type!r} depends on missing task {dependency!r}"
        )


class TaskDependencyCycleError(TaskGraphError):
    """Raised when processor task dependencies contain a cycle."""

    def __init__(self, cycle: Sequence[str]) -> None:
        self.cycle = tuple(cycle)
        super().__init__(
            f"Processor task dependency cycle detected: {' -> '.join(self.cycle)}"
        )


class TaskGraph:
    """Validated, deterministically ordered DAG of `ProcessorModule` instances."""

    def __init__(
        self,
        ordered: tuple[ProcessorModule, ...],
        by_type: dict[str, ProcessorModule],
        deps: dict[str, tuple[str, ...]],
        ancestors: dict[str, frozenset[str]],
    ) -> None:
        self._ordered = ordered
        self._by_type = by_type
        self._deps = deps
        self._ancestors = ancestors

    @classmethod
    def empty(cls) -> TaskGraph:
        """Return an empty task graph."""
        return cls((), {}, {}, {})

    @classmethod
    def build(cls, modules: Sequence[ProcessorModule]) -> TaskGraph:
        """Validate and topologically sort ``modules`` preserving registration tie-breaks."""
        by_type: dict[str, ProcessorModule] = {}
        reg_index: dict[str, int] = {}
        for idx, mod in enumerate(modules):
            task_type = _task_key(mod.task_type)
            if task_type in by_type:
                raise DuplicateTaskError(task_type)
            by_type[task_type] = mod
            reg_index[task_type] = idx

        deps: dict[str, tuple[str, ...]] = {}
        sorter: graphlib.TopologicalSorter[str] = graphlib.TopologicalSorter()
        for task_type, mod in by_type.items():
            unique_deps = tuple(dict.fromkeys(_task_key(d) for d in mod.depends_on))
            for dep in unique_deps:
                if dep not in by_type:
                    raise MissingTaskDependencyError(task_type, dep)
            deps[task_type] = unique_deps
            sorter.add(task_type, *unique_deps)

        try:
            sorter.prepare()
        except graphlib.CycleError as exc:
            raise TaskDependencyCycleError(exc.args[1]) from exc

        ready: list[tuple[int, str]] = []
        ordered: list[ProcessorModule] = []
        while sorter.is_active():
            for task_type in sorter.get_ready():
                heapq.heappush(ready, (reg_index[task_type], task_type))
            _, current = heapq.heappop(ready)
            ordered.append(by_type[current])
            sorter.done(current)

        ancestors: dict[str, frozenset[str]] = {}
        for mod in ordered:
            t = _task_key(mod.task_type)
            upstream: set[str] = set()
            for dep in deps[t]:
                upstream.add(dep)
                upstream.update(ancestors[dep])
            ancestors[t] = frozenset(upstream)

        return cls(
            ordered=tuple(ordered),
            by_type=by_type,
            deps=deps,
            ancestors=ancestors,
        )

    def __bool__(self) -> bool:
        return bool(self._ordered)

    def __len__(self) -> int:
        return len(self._ordered)

    @property
    def modules(self) -> tuple[ProcessorModule, ...]:
        """All registered modules in deterministic topological order."""
        return self._ordered

    def depends_on(self, task_type: str) -> tuple[str, ...]:
        """Return direct upstream `task_type` dependencies for ``task_type``."""
        return self._deps.get(_task_key(task_type), ())

    def ancestors(self, task_type: str) -> frozenset[str]:
        """Return transitive upstream dependencies for ``task_type``."""
        return self._ancestors.get(_task_key(task_type), frozenset())

    def descendants(self, task_type: str) -> frozenset[str]:
        """Return transitive downstream dependents for ``task_type``."""
        t = _task_key(task_type)
        return frozenset(
            candidate
            for candidate, upstream in self._ancestors.items()
            if t in upstream
        )

    def resolve_task_type(self, name: str) -> str | None:
        """Return canonical task type matching a registered stage's `task_type` or `name`."""
        lowered = name.strip().lower()
        if not lowered:
            return None
        for mod in self._ordered:
            key = _task_key(mod.task_type)
            if key.lower() == lowered or mod.name.lower() == lowered:
                return key
        return None

    def has_page_ancestor(self, task_type: str) -> bool:
        """Return True if any transitive upstream dependency has `TaskScope.PAGE`."""
        return any(
            self._by_type[ancestor].scope == TaskScope.PAGE
            for ancestor in self.ancestors(task_type)
        )

    def is_effectively_enabled(self, task_type: str) -> bool:
        """Return True iff ``task_type`` and all its upstream ancestors are enabled."""
        t = _task_key(task_type)
        mod = self._by_type.get(t)
        if mod is None or not mod.enabled:
            return False
        return all(self._by_type[ancestor].enabled for ancestor in self._ancestors[t])

    def subset(
        self,
        task_types: Iterable[str],
        *,
        exclude_page_dependent_file_tasks: bool = False,
    ) -> TaskGraph:
        """Return a closed sub-graph containing ``task_types`` and their upstream ancestors."""
        selected: set[str] = set()
        for raw in task_types:
            t = _task_key(raw)
            if t not in self._by_type:
                continue
            selected.add(t)
            selected.update(self._ancestors[t])

        if exclude_page_dependent_file_tasks:
            blocked_file_tasks = {
                t
                for t in selected
                if self._by_type[t].scope == TaskScope.FILE
                and self.has_page_ancestor(t)
            }
            if blocked_file_tasks:
                selected = {
                    t
                    for t in selected
                    if t not in blocked_file_tasks
                    and self._ancestors[t].isdisjoint(blocked_file_tasks)
                }

        ordered = [m for m in self._ordered if _task_key(m.task_type) in selected]
        return TaskGraph.build(ordered)


class ProcessorModule(abc.ABC):
    """Abstract base class for processor modules in the asynchronous pipeline.

    The pipeline follows a state-machine pattern:
    1. Orchestrator calls `run()`.
    2. `run()` calls `run_if_needed()` to check preconditions and status.
    3. If `run_if_needed()` is True, `run()` calls `process()` for the actual work.
    4. `run()` updates `SystemTaskDO` based on the outcome of `process()`.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique name of the module, used for logging."""

    @property
    @abc.abstractmethod
    def task_type(self) -> str:
        """The Task Type this module handles.
        Matches the `task_type` column in `f_system_task`.
        """

    @property
    def scope(self) -> TaskScope:
        """Execution granularity (`TaskScope.FILE` or `TaskScope.PAGE`)."""
        return TaskScope.FILE

    @property
    def depends_on(self) -> Sequence[str]:
        """Upstream `task_type` IDs that must succeed before this module runs."""
        return ()

    @property
    def enabled(self) -> bool:
        """Whether this module is currently enabled."""
        return True

    # TODO: Replace single-format boolean with a general document-kind capability
    # (e.g. `supported_document_kinds`) once additional formats like `.pdf` are added.
    @property
    def supports_standalone_images(self) -> bool:
        """Whether this module applies to standalone raster image files."""
        return True

    @property
    def version(self) -> str | None:
        """Optional version or model identifier for the module's output."""
        return None

    def get_task_key(
        self, page_index: int | None = None, page_id: str | None = None
    ) -> str:
        """Generate a unique task key for the given file and page.
        Returns 'page_{id}' if page_id exists.
        Returns 'global' if page_id is None.
        Legacy 'page_{index}' fallback is removed.
        """
        if page_id:
            return f"page_{page_id}"
        return "global"

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        *,
        user_id: int,
    ) -> bool:
        """Pre-flight check to determine if the module should execute.

        Returns:
            bool: True if `process()` should be called. False if the task is already
                  complete, prerequisites are missing, or the module is disabled.

        Semantic Expectations:
            - This should be a lightweight operation (DB lookup or config check).
            - It is used for feature gating (e.g., skip if API key is missing).
            - It is used for dependency management (e.g., OCR returns False if PNG is missing).
        """
        if not self.enabled:
            return False
        key = self.get_task_key(page_index, page_id)
        task = await get_task(session_manager, user_id, file_id, self.task_type, key)
        if (
            task
            and task.status == ProcessingStatus.COMPLETED
            and task.data == self.version
        ):
            return False
        return True

    @abc.abstractmethod
    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        **kwargs: object,
    ) -> None:
        """Execute the core module logic (CPU/IO intensive work).

        Expectations:
            - **Idempotency**: Must be safe to call multiple times for the same input.
            - **Atomic Updates**: Perform domain data updates within a DB transaction.
            - **Error Handling**:
                - **Raise Exceptions**: Raise descriptive exceptions for any failure.
                  Do not catch and log-then-swallow exceptions here.
                - **Recoverable vs Fatal**: Distinguish between transient errors
                  (which can be retried) and logic errors.
                - **SystemTask Status**: The `run` method automatically catches
                  exceptions, logs the traceback, and sets the `f_system_task`
                  status to `FAILED` with the error message.
        """

    async def run(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        *,
        user_id: int,
        **kwargs: object,
    ) -> bool:
        """The entry point for executing a module.

        Logic:
            1. If `run_if_needed()` returns False, returns True (graceful skip).
            2. Calls `process()`.
            3. On success, marks task `COMPLETED` and returns True.
            4. On failure, marks task `FAILED` with error message and returns False.

        Returns:
            bool: True if the process is completed or skipped. False if it failed.
                  A False return value stalls dependent tasks for this page/file.
        """
        if not self.enabled:
            return True

        if not await self.run_if_needed(
            file_id, session_manager, page_index, page_id, user_id=user_id
        ):
            PROCESSOR_TASKS_TOTAL.labels(module=self.name, status="skipped").inc()
            return True

        key = self.get_task_key(page_index, page_id)
        logger.info(f"Running {self.name} for file {file_id} (key={key})")

        start_time = time.monotonic()
        status_str = "failure"
        try:
            await self.process(
                file_id, session_manager, page_index, page_id=page_id, **kwargs
            )
            await update_task_status(
                session_manager,
                user_id,
                file_id,
                self.task_type,
                key,
                ProcessingStatus.COMPLETED,
                data=self.version,
            )
            status_str = "success"
            return True
        except asyncio.CancelledError:
            status_str = "cancelled"
            raise
        except Exception as e:
            logger.error(f"Error in {self.name} for file {file_id}: {e}", exc_info=True)
            msg = str(e)
            error_detail = f"{type(e).__name__}: {msg}" if msg else type(e).__name__
            await update_task_status(
                session_manager,
                user_id,
                file_id,
                self.task_type,
                key,
                ProcessingStatus.FAILED,
                error_detail,
            )
            return False
        finally:
            duration = time.monotonic() - start_time
            PROCESSOR_TASKS_TOTAL.labels(module=self.name, status=status_str).inc()
            if status_str != "cancelled":
                PROCESSOR_TASK_DURATION_SECONDS.labels(module=self.name).observe(
                    duration
                )

    async def cleanup_file(
        self,
        file_id: int,
        user_id: int,
        session_manager: DatabaseSessionManager,
    ) -> None:
        """Clean up module-owned domain artifacts when a note file is deleted."""
        return None
