import abc
from typing import Optional

from supernote.server.db.session import DatabaseSessionManager


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

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
    ) -> bool:
        """
        Check if the task needs to be run.
        This checks BOTH the SystemTaskDO status (Intent) AND the end-state (Reality).
        """
        # TODO: Implement base logic here to check SystemTaskDO
        # For now, we delegate to abstract check_end_state?
        # Actually, let's keep it simple for now and just delegate to specific modules
        # but with this new name to signify the hybrid check.
        # Default to True so subclasses can implement basic logic
        return True

    @abc.abstractmethod
    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
        **kwargs: object,
    ) -> None:
        """Execute the module logic."""
        pass
