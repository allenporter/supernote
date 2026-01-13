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

    @abc.abstractmethod
    async def should_process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
    ) -> bool:
        """Determine if this module needs to run for the given page."""
        pass

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
