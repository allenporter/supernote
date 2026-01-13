import asyncio
import io
import logging
import time
from functools import partial
from typing import Optional

from sqlalchemy import select

from supernote.notebook.converter import ImageConverter
from supernote.notebook.parser import load_notebook
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import SystemTaskDO
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

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
    ) -> bool:
        """
        Check if PNG conversion is needed.
        Returns True if the task is not COMPLETED or if force re-process is needed.
        """
        if page_index is None:
            return False

        task_key = f"page_{page_index}"
        async with session_manager.session() as session:
            task = (
                (
                    await session.execute(
                        select(SystemTaskDO)
                        .where(SystemTaskDO.file_id == file_id)
                        .where(SystemTaskDO.task_type == self.task_type)
                        .where(SystemTaskDO.key == task_key)
                    )
                )
                .scalars()
                .first()
            )
            if task and task.status == "COMPLETED":
                # Check if file exists in blob storage?
                # Optimization: Trust DB for now, or check blob existence if robust.
                return False

        return True

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
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

        logger.info(f"Starting {self.name} for file {file_id} page {page_index}")

        # 1. Resolve file path (Logic shared with PageHashingModule - TODO: refactor to common util)
        async with session_manager.session() as session:
            result = await session.execute(
                select(UserFileDO).where(UserFileDO.id == file_id)
            )
            user_file = result.scalars().first()
            if not user_file or not user_file.storage_key:
                logger.error(f"File {file_id} not found or missing storage_key")
                return
            storage_key = user_file.storage_key

        try:
            abs_path = self.file_service.blob_storage.get_blob_path(
                USER_DATA_BUCKET, storage_key
            )
        except Exception as e:
            logger.error(f"Failed to resolve blob path for {file_id}: {e}")
            return

        if not abs_path.exists():
            logger.error(f"File {abs_path} does not exist on disk")
            return

        # 2. Run Conversion in Thread Pool
        try:
            loop = asyncio.get_running_loop()
            png_data = await loop.run_in_executor(
                None, partial(_convert_helper, str(abs_path), page_index)
            )
        except Exception as e:
            logger.error(f"Failed to convert page {page_index} of {file_id}: {e}")
            await self._update_task_status(
                session_manager, file_id, page_index, "FAILED", str(e)
            )
            return

        # 3. Upload to Blob Storage
        # Path format: {file_id}/pages/{page_index}.png
        blob_path = get_page_png_path(file_id, page_index)
        try:
            await self.file_service.blob_storage.put(CACHE_BUCKET, blob_path, png_data)
        except Exception as e:
            logger.error(f"Failed to upload PNG for {file_id} page {page_index}: {e}")
            await self._update_task_status(
                session_manager, file_id, page_index, "FAILED", f"Upload failed: {e}"
            )
            return

        # 4. Update Task Status
        await self._update_task_status(
            session_manager, file_id, page_index, "COMPLETED"
        )
        logger.info(f"Successfully converted page {page_index} of {file_id} to PNG")

    async def _update_task_status(
        self,
        session_manager: DatabaseSessionManager,
        file_id: int,
        page_index: int,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        task_key = f"page_{page_index}"
        async with session_manager.session() as session:
            existing_task = (
                (
                    await session.execute(
                        select(SystemTaskDO)
                        .where(SystemTaskDO.file_id == file_id)
                        .where(SystemTaskDO.task_type == self.task_type)
                        .where(SystemTaskDO.key == task_key)
                    )
                )
                .scalars()
                .first()
            )

            if not existing_task:
                existing_task = SystemTaskDO(
                    file_id=file_id,
                    task_type=self.task_type,
                    key=task_key,
                    status=status,
                    last_error=error,
                )
                session.add(existing_task)
            else:
                existing_task.status = status
                existing_task.last_error = error
                existing_task.update_time = int(time.time() * 1000)

            await session.commit()
