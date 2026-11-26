"""Stage 2 of the `.note` processing pipeline: per-page PNG rasterization (`TaskType.PNG_CONVERSION`).

`PngConversionModule` converts modified `.note` pages into PNG images using
`supernote.notebook.converter.ImageConverter` in a thread pool and stores the rendered
bytes in `CACHE_BUCKET` (`supernote.server.services.blob.BlobStorage`). These cached PNGs
serve both Web UI page previews and the downstream `supernote.server.components.transcript.processor.OcrModule`.
See `supernote.guides.note_processing_design`.
"""

import asyncio
import io
import logging
from functools import partial

from sqlalchemy import select

from supernote.models.base import TaskType
from supernote.notebook.converter import ImageConverter
from supernote.notebook.parser import load_notebook
from supernote.server.components.ai import OCR_MODEL_KEY, AiModelsUpdatedEvent
from supernote.server.components.processor import (
    ProcessorModule,
    ProcessorRegistrar,
    TaskScope,
)
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.core import ServerCore
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.keys import COMPONENT_LOADER_KEY
from supernote.server.services.file import FileService
from supernote.server.utils.image import (
    MAX_ALLOWED_IMAGE_DIMENSION,
    MAX_SOURCE_IMAGE_BYTES,
    is_image_filename,
    normalize_image_to_png,
)
from supernote.server.utils.paths import get_page_png_path

from .service import CONVERSION_SERVICE_KEY

logger = logging.getLogger(__name__)

# Use zlib compression level 1 (fastest) to minimize CPU overhead during background PNG rendering.
PNG_COMPRESS_LEVEL = 1


def _convert_helper(path: str, page_index: int) -> bytes:
    # Use loose policy to attempt parsing even if signature is unknown
    notebook = load_notebook(path, policy="loose", page_number=page_index)
    converter = ImageConverter(notebook)  # type: ignore[no-untyped-call]
    img = converter.convert(page_index)  # type: ignore[no-untyped-call]
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=PNG_COMPRESS_LEVEL)
    return buf.getvalue()


class PngConversionModule(ProcessorModule):
    def __init__(self, file_service: FileService, *, enabled: bool = True) -> None:
        self.file_service = file_service
        self._enabled = enabled

    @property
    def name(self) -> str:
        return "PngConversionModule"

    @property
    def task_type(self) -> TaskType:
        return TaskType.PNG_CONVERSION

    @property
    def scope(self) -> TaskScope:
        return TaskScope.PAGE

    @property
    def depends_on(self) -> tuple[TaskType, ...]:
        return (TaskType.PAGE_HASHING,)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def version(self) -> str | None:
        return "v2"

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        *,
        user_id: int,
    ) -> bool:
        if await super().run_if_needed(
            file_id, session_manager, page_index, page_id, user_id=user_id
        ):
            return True
        if page_id:
            png_path = get_page_png_path(file_id, page_id)
            if not await self.file_service.blob_storage.exists(CACHE_BUCKET, png_path):
                return True
        return False

    async def cleanup_file(
        self,
        file_id: int,
        user_id: int,
        session_manager: DatabaseSessionManager,
    ) -> None:
        """Delete cached page PNG blobs for a deleted note."""
        async with session_manager.session() as session:
            result = await session.execute(
                select(NotePageContentDO.page_id).where(
                    NotePageContentDO.file_id == file_id
                )
            )
            page_ids = result.scalars().all()

        for page_id in page_ids:
            if not page_id:
                continue
            png_path = get_page_png_path(file_id, page_id)
            try:
                await self.file_service.blob_storage.delete(CACHE_BUCKET, png_path)
            except (FileNotFoundError, OSError) as e:
                logger.warning(
                    f"Failed to delete PNG for {file_id} page {page_id}: {e}"
                )

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
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
            file_name = user_file.file_name

            if page_id is None:
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

        loop = asyncio.get_running_loop()
        if is_image_filename(file_name):
            raw_size = abs_path.stat().st_size
            if raw_size > MAX_SOURCE_IMAGE_BYTES:
                raise ValueError(
                    f"Image file {file_id} exceeds maximum size of {MAX_SOURCE_IMAGE_BYTES} bytes"
                )
            raw_bytes = await loop.run_in_executor(None, abs_path.read_bytes)
            png_data, _, _ = await loop.run_in_executor(
                None,
                partial(
                    normalize_image_to_png,
                    raw_bytes,
                    max_dimension=MAX_ALLOWED_IMAGE_DIMENSION,
                ),
            )
        else:
            png_data = await loop.run_in_executor(
                None, partial(_convert_helper, str(abs_path), page_index)
            )

        # Upload to Blob Storage
        blob_path = get_page_png_path(file_id, page_id)
        await self.file_service.blob_storage.put(CACHE_BUCKET, blob_path, png_data)
        logger.info(
            f"Successfully converted page {page_index} ({page_id}) of {file_id} to PNG"
        )


async def async_setup_processor(
    core: ServerCore,
    registrar: ProcessorRegistrar,
) -> None:
    """Register `PngConversionModule` with the `"processor"` platform."""
    ocr_model = core.app.get(OCR_MODEL_KEY)
    conversion_service = core.app[CONVERSION_SERVICE_KEY]
    web_ui_loaded = core.app[COMPONENT_LOADER_KEY].get("web_ui") is not None
    png_enabled = (ocr_model is not None) or (
        web_ui_loaded and conversion_service.notebook_preview
    )
    module = PngConversionModule(file_service=core.file_service, enabled=png_enabled)

    async def _on_ai_models_updated(event: AiModelsUpdatedEvent) -> None:
        module.enabled = (event.ocr_model is not None) or (
            web_ui_loaded and conversion_service.notebook_preview
        )

    core.event_bus.subscribe(AiModelsUpdatedEvent, _on_ai_models_updated, inline=True)
    registrar.register_module(module)
