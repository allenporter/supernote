import abc
import logging
from typing import Optional

from supernote.server.db.session import DatabaseSessionManager
from supernote.server.utils.tasks import get_task, update_task_status

logger = logging.getLogger(__name__)


class ProcessorModule(abc.ABC):
    """Abstract base class for processor modules."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique name of the module."""
        pass

    @property
    @abc.abstractmethod
    def task_type(self) -> str:
        """The Task Type this module handles (e.g., 'PNG', 'OCR')."""
        pass

    def get_task_key(self, page_index: Optional[int] = None) -> str:
        """Generate a unique task key for the given file and page."""
        return f"page_{page_index}" if page_index is not None else "global"

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
    ) -> bool:
        """
        Check if the task needs to be run by checking SystemTaskDO status.
        Subclasses can override this for additional prerequisite checks.
        """
        key = self.get_task_key(page_index)
        task = await get_task(session_manager, file_id, self.task_type, key)
        if task and task.status == "COMPLETED":
            return False
        return True

    @abc.abstractmethod
    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
        **kwargs: object,
    ) -> None:
        """Execute the module logic. Should not worry about status updates unless specific failure cases arise."""
        pass

    async def run(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
        **kwargs: object,
    ) -> bool:
        """
        The entry point for executing a module.
        Handles run_if_needed check, status updates, and error handling.
        Returns True if the process completed successfully (or was already completed).
        """
        if not await self.run_if_needed(file_id, session_manager, page_index):
            return True

        key = self.get_task_key(page_index)
        logger.info(f"Running {self.name} for file {file_id} (key={key})")

        try:
            await self.process(file_id, session_manager, page_index, **kwargs)
            await update_task_status(
                session_manager, file_id, self.task_type, key, "COMPLETED"
            )
            return True
        except Exception as e:
            logger.error(f"Error in {self.name} for file {file_id}: {e}", exc_info=True)
            await update_task_status(
                session_manager, file_id, self.task_type, key, "FAILED", str(e)
            )
            return False
