import asyncio
import io
import logging
from functools import partial
from typing import Optional

from sqlalchemy import select

from supernote.notebook.converter import ImageConverter
from supernote.notebook.parser import load_notebook
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.utils.paths import get_page_png_path

logger = logging.getLogger(__name__)


def _convert_helper(path: str, page_index: int) -> bytes:
    # Use loose policy to attempt parsing even if signature is unknown
    notebook = load_notebook(path, policy="loose")  # type: ignore[no-untyped-call]
    converter = ImageConverter(notebook)  # type: ignore[no-untyped-call]
    img = converter.convert(page_index)  # type: ignore[no-untyped-call]
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class PngConversionModule(ProcessorModule):
    def __init__(self, file_service: FileService) -> None:
        self.file_service = file_service

    @property
    def name(self) -> str:
        return "PngConversionModule"

    @property
    def task_type(self) -> str:
        return "PNG_CONVERSION"

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
        page_id: Optional[str] = None,
        **kwargs: object,
    ) -> None:
        """
        Converts a specific page of the .note file to PNG and saves it to blob storage.
        """
        if page_index is None:
            logger.warning(
                f"PngConversionModule requires page_index for file {file_id}"
            )
            return

        # Resolve file path
        async with session_manager.session() as session:
            result = await session.execute(
                select(UserFileDO).where(UserFileDO.id == file_id)
            )
            user_file = result.scalars().first()
            if not user_file or not user_file.storage_key:
                logger.error(f"File {file_id} not found or missing storage_key")
                return
            storage_key = user_file.storage_key

            # Get Page ID for stable path
            page_result = await session.execute(
                select(NotePageContentDO.page_id).where(
                    NotePageContentDO.file_id == file_id,
                    NotePageContentDO.page_index == page_index,
                )
            )
            page_id = page_result.scalars().first()
            if not page_id:
                logger.error(f"Page ID not found for {file_id} index {page_index}")
                return

        try:
            abs_path = self.file_service.blob_storage.get_blob_path(
                USER_DATA_BUCKET, storage_key
            )
        except Exception as e:
            logger.error(f"Failed to resolve blob path for {file_id}: {e}")
            raise

        if not abs_path.exists():
            logger.error(f"File {abs_path} does not exist on disk")
            raise FileNotFoundError(f"File {abs_path} does not exist on disk")

        # Run Conversion in Thread Pool
        loop = asyncio.get_running_loop()
        png_data = await loop.run_in_executor(
            None, partial(_convert_helper, str(abs_path), page_index)
        )

        # Upload to Blob Storage
        blob_path = get_page_png_path(file_id, page_id)
        await self.file_service.blob_storage.put(CACHE_BUCKET, blob_path, png_data)
        logger.info(
            f"Successfully converted page {page_index} ({page_id}) of {file_id} to PNG"
        )
