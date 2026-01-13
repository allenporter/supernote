from typing import Optional

from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.processor_modules import ProcessorModule


class PageHashingModule(ProcessorModule):
    @property
    def name(self) -> str:
        return "PageHashingModule"

    @property
    def task_type(self) -> str:
        return "HASHING"

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
    ) -> bool:
        # Placeholder: Run once? Or logic to check DB
        return False

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
        **kwargs: object,
    ) -> None:
        pass
