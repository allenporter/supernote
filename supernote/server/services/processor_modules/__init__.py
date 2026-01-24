import abc
import logging
from typing import Optional

from supernote.models.base import ProcessingStatus
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.utils.tasks import get_task, update_task_status

logger = logging.getLogger(__name__)


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
        pass

    @property
    @abc.abstractmethod
    def task_type(self) -> str:
        """The Task Type this module handles (e.g., 'PNG', 'OCR').
        Matches the `task_type` column in `f_system_task`.
        """
        pass

    def get_task_key(
        self, page_index: Optional[int] = None, page_id: Optional[str] = None
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
        page_index: Optional[int] = None,
        page_id: Optional[str] = None,
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
        key = self.get_task_key(page_index, page_id)
        task = await get_task(session_manager, file_id, self.task_type, key)
        if task and task.status == ProcessingStatus.COMPLETED:
            return False
        return True

    @abc.abstractmethod
    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
        page_id: Optional[str] = None,
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
        pass

    async def run(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
        page_id: Optional[str] = None,
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
                  A False return value usually stalls the pipeline for this page/file.
        """
        if not await self.run_if_needed(file_id, session_manager, page_index, page_id):
            return True

        key = self.get_task_key(page_index, page_id)
        logger.info(f"Running {self.name} for file {file_id} (key={key})")

        try:
            await self.process(
                file_id, session_manager, page_index, page_id=page_id, **kwargs
            )
            await update_task_status(
                session_manager,
                file_id,
                self.task_type,
                key,
                ProcessingStatus.COMPLETED,
            )
            return True
        except Exception as e:
            logger.error(f"Error in {self.name} for file {file_id}: {e}", exc_info=True)
            await update_task_status(
                session_manager,
                file_id,
                self.task_type,
                key,
                ProcessingStatus.FAILED,
                str(e),
            )
            return False
