import asyncio
import json
import logging
import time
from functools import partial

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from supernote.models.base import TaskType
from supernote.notebook import Notebook, load_notebook
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NoteMetadataDO,
    NotePageContentDO,
    NotePageMetadataDO,
    SystemTaskDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.utils.hashing import get_md5_hash
from supernote.server.utils.note_content import keyword_to_vo, link_to_vo, title_to_vo
from supernote.server.utils.paths import get_page_png_path, is_valid_page_id

logger = logging.getLogger(__name__)


def _load_notebook_helper(path: str) -> Notebook:
    return load_notebook(path, policy="loose")


class PageHashingModule(ProcessorModule):
    """Module responsible for detecting changes in .note files at the page level.

    This module performs the following:
    - Parses the binary .note file using `load_notebook(..., policy="loose")`.
    - Persists notebook-level metadata (`NoteMetadataDO`) and per-page structural/ink
      metadata (`NotePageMetadataDO`) across all pages `0..total_pages - 1`.
    - Computes a unique MD5 hash for each page based on its layer metadata.
    - Updates the `NotePageContentDO` table:
        - Creates entries for new pages.
        - Updates hashes for changed pages and invalidates downstream data (OCR, Embeddings) to trigger reprocessing.
        - Removes entries for deleted pages.
    - Updates the `SystemTaskDO` status for the 'HASHING' task (handled by base class).

    This module acts as the entry point and "change detector" for the incremental processing pipeline.
    """

    def __init__(self, file_service: FileService) -> None:
        self.file_service = file_service

    @property
    def name(self) -> str:
        return "PageHashingModule"

    @property
    def task_type(self) -> TaskType:
        return TaskType.PAGE_HASHING

    @property
    def version(self) -> str:
        return "v2"

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
    ) -> bool:
        """Hashing acts as the change detector, so it MUST run every time the file is processed."""
        return True

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        **kwargs: object,
    ) -> None:
        """Parses the .note file, persists metadata, computes page hashes, and updates NotePageContentDO."""
        logger.info(f"Starting PageHashingModule for file_id={file_id}")

        async with session_manager.session() as session:
            result = await session.execute(
                select(UserFileDO).where(UserFileDO.id == file_id)
            )
            user_file = result.scalars().first()
            if not user_file:
                logger.error(f"File {file_id} not found in DB")
                return

            user_id = user_file.user_id
            storage_key = user_file.storage_key
            if not storage_key:
                logger.error(f"File {file_id} has no storage_key")
                return

        abs_path = self.file_service.blob_storage.get_blob_path(
            USER_DATA_BUCKET, storage_key
        )

        if not abs_path.exists():
            logger.error(f"File {abs_path} does not exist on disk")
            raise FileNotFoundError(f"File {abs_path} does not exist on disk")

        # Load .note file in thread pool (extracts metadata + layer bitmaps for ink detection)
        loop = asyncio.get_running_loop()
        notebook = await loop.run_in_executor(
            None, partial(_load_notebook_helper, str(abs_path))
        )
        metadata = notebook.metadata
        total_pages = metadata.total_pages
        equipment = metadata.header.apply_equipment
        equipment_str = str(equipment) if equipment is not None else None
        header_json = json.dumps(metadata.header.to_wire_dict(), ensure_ascii=False)
        footer_json = json.dumps(metadata.footer.to_wire_dict(), ensure_ascii=False)

        now = int(time.time() * 1000)
        async with session_manager.session() as session:
            upsert_meta = (
                sqlite_insert(NoteMetadataDO)
                .values(
                    user_id=user_id,
                    file_id=file_id,
                    native_file_id=notebook.file_id,
                    file_type=notebook.type,
                    equipment=equipment_str,
                    signature=notebook.signature,
                    width=notebook.width,
                    height=notebook.height,
                    total_pages=total_pages,
                    recogn_language=metadata.header.file_recogn_language,
                    is_realtime_recognition=notebook.is_realtime_recognition(),
                    header_json=header_json,
                    footer_json=footer_json,
                    create_time=now,
                    update_time=now,
                )
                .on_conflict_do_update(
                    index_elements=["user_id", "file_id"],
                    set_={
                        "native_file_id": notebook.file_id,
                        "file_type": notebook.type,
                        "equipment": equipment_str,
                        "signature": notebook.signature,
                        "width": notebook.width,
                        "height": notebook.height,
                        "total_pages": total_pages,
                        "recogn_language": metadata.header.file_recogn_language,
                        "is_realtime_recognition": notebook.is_realtime_recognition(),
                        "header_json": header_json,
                        "footer_json": footer_json,
                        "update_time": now,
                    },
                )
            )
            await session.execute(upsert_meta)

            for i in range(total_pages):
                page_info = metadata.pages[i]
                page_obj = notebook.pages[i]
                raw_page_id = page_info.page_id or ""
                style_hash = page_obj.style_hash or None
                orientation = str(page_obj.orientation)
                recogn_status = int(page_obj.recogn_status)
                page_json = json.dumps(page_info.to_wire_dict(), ensure_ascii=False)
                keywords_json = json.dumps(
                    [keyword_to_vo(kw).to_dict() for kw in page_obj.keywords],
                    ensure_ascii=False,
                )
                titles_json = json.dumps(
                    [title_to_vo(t).to_dict() for t in page_obj.titles],
                    ensure_ascii=False,
                )
                links_json = json.dumps(
                    [link_to_vo(lk).to_dict() for lk in page_obj.links],
                    ensure_ascii=False,
                )

                upsert_page_meta = (
                    sqlite_insert(NotePageMetadataDO)
                    .values(
                        user_id=user_id,
                        file_id=file_id,
                        page_index=i,
                        page_id=raw_page_id,
                        page_style=page_obj.style,
                        style_hash=style_hash,
                        orientation=orientation,
                        recogn_status=recogn_status,
                        has_ink=page_obj.has_ink,
                        has_drawables=page_obj.has_drawables,
                        has_textbox=page_obj.has_textbox,
                        has_vector_graph=page_obj.has_vector_graph,
                        has_content=page_obj.has_content,
                        page_json=page_json,
                        keywords_json=keywords_json,
                        titles_json=titles_json,
                        links_json=links_json,
                        create_time=now,
                        update_time=now,
                    )
                    .on_conflict_do_update(
                        index_elements=["user_id", "file_id", "page_index"],
                        set_={
                            "page_id": raw_page_id,
                            "page_style": page_obj.style,
                            "style_hash": style_hash,
                            "orientation": orientation,
                            "recogn_status": recogn_status,
                            "has_ink": page_obj.has_ink,
                            "has_drawables": page_obj.has_drawables,
                            "has_textbox": page_obj.has_textbox,
                            "has_vector_graph": page_obj.has_vector_graph,
                            "has_content": page_obj.has_content,
                            "page_json": page_json,
                            "keywords_json": keywords_json,
                            "titles_json": titles_json,
                            "links_json": links_json,
                            "update_time": now,
                        },
                    )
                )
                await session.execute(upsert_page_meta)

            await session.execute(
                delete(NotePageMetadataDO).where(
                    NotePageMetadataDO.user_id == user_id,
                    NotePageMetadataDO.file_id == file_id,
                    NotePageMetadataDO.page_index >= total_pages,
                )
            )

            if not metadata.pages:
                await session.commit()
                return

            existing_pages = await session.execute(
                select(NotePageContentDO).where(NotePageContentDO.file_id == file_id)
            )
            existing_map = {p.page_id: p for p in existing_pages.scalars().all()}

            current_page_ids = set()
            any_page_changed = False

            for i in range(total_pages):
                page_info = metadata.pages[i]
                page_id_val = page_info.page_id

                if not isinstance(page_id_val, str) or not is_valid_page_id(
                    page_id_val
                ):
                    logger.warning(
                        f"Page {i} of file {file_id} has missing or invalid PAGEID."
                    )
                    continue

                current_page_ids.add(page_id_val)

                page_hash_input = str(page_info.to_wire_dict())
                current_hash = get_md5_hash(page_hash_input)

                if page_id_val in existing_map:
                    row = existing_map[page_id_val]

                    if row.page_index != i:
                        logger.info(
                            f"Page {page_id_val} moved from {row.page_index} to {i}"
                        )
                        row.page_index = i
                        any_page_changed = True

                    if row.content_hash != current_hash:
                        logger.info(
                            f"Page {page_id_val} (idx {i}) changed. Resetting content."
                        )
                        row.content_hash = current_hash
                        row.text_content = None
                        row.embedding = None
                        row.embedding_model = None
                        any_page_changed = True

                        page_task_key = f"page_{page_id_val}"
                        await session.execute(
                            delete(SystemTaskDO)
                            .where(SystemTaskDO.file_id == file_id)
                            .where(SystemTaskDO.key == page_task_key)
                        )
                else:
                    logger.info(f"New page {page_id_val} at index {i} detected.")
                    any_page_changed = True
                    new_content = NotePageContentDO(
                        file_id=file_id,
                        page_index=i,
                        page_id=page_id_val,
                        content_hash=current_hash,
                        text_content=None,
                        embedding=None,
                        embedding_model=None,
                    )
                    session.add(new_content)

            for pid, row in existing_map.items():
                if pid not in current_page_ids:
                    logger.info(f"Page {pid} deleted (was at {row.page_index}).")
                    any_page_changed = True
                    await session.delete(row)

                    png_path = get_page_png_path(file_id, pid)
                    try:
                        await self.file_service.blob_storage.delete(
                            CACHE_BUCKET, png_path
                        )
                    except (FileNotFoundError, OSError) as e:
                        logger.warning(f"Failed to delete orphan PNG {pid}: {e}")

                    await session.execute(
                        delete(SystemTaskDO)
                        .where(SystemTaskDO.file_id == file_id)
                        .where(SystemTaskDO.key == f"page_{pid}")
                    )

            if any_page_changed:
                await session.execute(
                    delete(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == TaskType.SUMMARY_GENERATION.value)
                )

            await session.commit()
