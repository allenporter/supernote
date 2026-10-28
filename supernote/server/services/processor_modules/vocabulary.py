import asyncio
import logging

from supernote.models.base import TaskType
from supernote.notebook.fileformat import KEY_KEYWORDS, Keyword
from supernote.notebook.parser import parse_metadata
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.services.vocabulary import VocabularyService

logger = logging.getLogger(__name__)


def _read_keywords(path: str) -> list[str]:
    with open(path, "rb") as f:
        metadata = parse_metadata(f)
    entries = (metadata.footer or {}).get(KEY_KEYWORDS)
    if not isinstance(entries, list):
        return []
    keywords = [Keyword(entry).get_keyword() for entry in entries]
    return [keyword for keyword in keywords if keyword]


class VocabularyHarvestModule(ProcessorModule):
    """Adds the keywords typed on the device to the owner's vocabulary.

    Runs on every pass, before page OCR: a keyword can be added or edited
    without changing any page's content hash, and a new keyword should be
    available to the OCR of the same upload.
    """

    def __init__(
        self, file_service: FileService, vocabulary_service: VocabularyService
    ) -> None:
        self.file_service = file_service
        self.vocabulary_service = vocabulary_service

    @property
    def name(self) -> str:
        return "VocabularyHarvestModule"

    @property
    def task_type(self) -> TaskType:
        return TaskType.VOCABULARY_HARVEST

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
    ) -> bool:
        return self.enabled

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        **kwargs: object,
    ) -> None:
        async with session_manager.session() as session:
            user_file = await session.get(UserFileDO, file_id)
            if not user_file or not user_file.storage_key:
                return
            user_id = user_file.user_id
            storage_key = user_file.storage_key

        path = self.file_service.blob_storage.get_blob_path(
            USER_DATA_BUCKET, storage_key
        )
        keywords = await asyncio.to_thread(_read_keywords, str(path))
        await self.vocabulary_service.harvest(user_id, file_id, keywords)
