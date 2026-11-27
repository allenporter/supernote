"""On-demand `.note` to PNG and PDF conversion service with blob cache lookup.

`ConversionService` serves page PNG previews and multi-page vector PDF exports
of notes and summary handwriting `.mark` blobs for hardware devices, the Web UI,
the summary component, and signed OSS URLs. It checks `CACHE_BUCKET` via
`supernote.server.services.blob.BlobStorage` first and delegates missing page
PNGs to `supernote.server.components.processor.ProcessorService`
or renders PDFs in a worker thread via `supernote.notebook.converter.PdfConverter`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web
from sqlalchemy import select

from supernote.models.base import TaskType
from supernote.models.summary import SummaryItem
from supernote.notebook import PdfConverter, PngConverter
from supernote.notebook import load as load_notebook
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import FileError, FileNotFound
from supernote.server.services.blob import BlobStorage
from supernote.server.services.user import UserService
from supernote.server.services.vfs import VirtualFileSystem
from supernote.server.utils.image import (
    DEFAULT_MAX_IMAGE_DIMENSION,
    MAX_ALLOWED_IMAGE_DIMENSION,
    MAX_SOURCE_IMAGE_BYTES,
    MIN_ALLOWED_IMAGE_DIMENSION,
    STANDALONE_IMAGE_PAGE_ID,
    is_image_filename,
    normalize_image_to_png,
)
from supernote.server.utils.paths import (
    get_conversion_pdf_path,
    get_page_png_path,
    get_summary_handwriting_prefix,
)

if TYPE_CHECKING:
    from supernote.server.components.processor import ProcessorService

__all__ = [
    "CONVERSION_SERVICE_KEY",
    "ConversionService",
    "ConvertedBlob",
    "PageImage",
]


@dataclass(frozen=True)
class ConvertedBlob:
    """Resolved CACHE_BUCKET blob reference and user-facing download filename."""

    storage_key: str
    file_name: str


@dataclass(frozen=True)
class PageImage:
    """Resolved and normalized PNG image for a notebook page or standalone image file."""

    file_name: str
    """Original VFS filename of the source file."""
    page_index: int
    """0-based page index (`0` for standalone image files)."""
    page_id: str
    """Stable page identifier (`'img'` for standalone image files)."""
    png_bytes: bytes
    """Normalized PNG image payload."""
    width: int
    """Normalized image width in pixels."""
    height: int
    """Normalized image height in pixels."""


def _convert_note_to_pdf_sync(blob_content: bytes, page_no_list: list[int]) -> bytes:
    """Parse a note file and convert requested pages to PDF in a worker thread."""
    note = load_notebook(BytesIO(blob_content), policy="loose")
    converter = PdfConverter(note)
    return converter.convert(page_no_list if page_no_list else -1)


def _convert_note_to_png_pages_sync(blob_content: bytes) -> list[bytes]:
    """Helper to parse a note file and render every page to PNG in a synchronous context."""
    note = load_notebook(BytesIO(blob_content), policy="loose")
    converter = PngConverter(note)  # type: ignore[no-untyped-call]
    pages = []
    for page_no in range(note.total_pages):
        buf = BytesIO()
        converter.convert(page_no).save(buf, format="PNG")  # type: ignore[no-untyped-call]
        pages.append(buf.getvalue())
    return pages


class ConversionService:
    """Manages on-demand note conversions (PNG and PDF) and CACHE_BUCKET resolution."""

    def __init__(
        self,
        session_manager: DatabaseSessionManager,
        blob_storage: BlobStorage,
        user_service: UserService,
        processor_service: ProcessorService,
        *,
        notebook_preview: bool = True,
    ) -> None:
        self.session_manager = session_manager
        self.blob_storage = blob_storage
        self.user_service = user_service
        self.processor_service = processor_service
        self.notebook_preview = notebook_preview

    async def _get_required_note_node(
        self, user: str, file_id: int
    ) -> tuple[int, UserFileDO]:
        """Resolve and validate a note VFS node owned by user, raising on missing metadata."""
        user_id = await self.user_service.get_user_id(user)
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            node = await vfs.get_node_by_id(user_id, file_id)
            if not node or node.is_folder == "Y":
                raise FileNotFound(f"Note file {file_id} not found")
            if not node.md5:
                raise FileError(f"Note file {file_id} is missing MD5 hash")
            if node.storage_key is None:
                raise FileNotFound(f"Note file {file_id} has no content")
            return user_id, node

    async def _get_note_node_or_none(
        self, user: str, file_id: int
    ) -> tuple[int, UserFileDO] | None:
        """Resolve a note VFS node owned by user, returning None if user or file is not found."""
        try:
            user_id = await self.user_service.get_user_id(user)
        except ValueError:
            return None
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            node = await vfs.get_node_by_id(user_id, file_id)
            if not node or node.is_folder == "Y":
                return None
            return user_id, node

    async def convert_note_to_png(
        self,
        user: str,
        file_id: int,
        page_indices: set[int] | None = None,
    ) -> list[int]:
        """Ensure requested (or all) pages of a note are converted to PNG in CACHE_BUCKET and return page numbers."""
        user_id, _ = await self._get_required_note_node(user, file_id)

        if not await self.processor_service.process_file(
            file_id,
            user_id=user_id,
            task_types={TaskType.PAGE_HASHING, TaskType.PNG_CONVERSION},
            page_indices=page_indices,
        ):
            raise FileError(f"Failed to convert note file {file_id} to PNG")

        async with self.session_manager.session() as session:
            stmt = (
                select(NotePageContentDO.page_index)
                .where(
                    NotePageContentDO.file_id == file_id,
                    NotePageContentDO.page_id != "",
                )
                .order_by(NotePageContentDO.page_index)
            )
            if page_indices is not None:
                stmt = stmt.where(NotePageContentDO.page_index.in_(page_indices))
            return list((await session.execute(stmt)).scalars().all())

    async def get_note_png_page(
        self, user: str, file_id: int, page_no: int
    ) -> ConvertedBlob | None:
        """Resolve the CACHE_BUCKET blob and user-friendly filename for a converted note page PNG."""
        resolved = await self._get_note_node_or_none(user, file_id)
        if not resolved:
            return None
        _, node = resolved

        async with self.session_manager.session() as session:
            stmt = select(NotePageContentDO.page_id).where(
                NotePageContentDO.file_id == file_id,
                NotePageContentDO.page_index == page_no,
            )
            page_id = (await session.execute(stmt)).scalar_one_or_none()

        if not page_id:
            return None
        png_key = get_page_png_path(file_id, page_id)
        if not await self.blob_storage.exists(CACHE_BUCKET, png_key):
            return None
        stem = Path(node.file_name).stem or f"note_{file_id}"
        return ConvertedBlob(
            storage_key=png_key,
            file_name=f"{stem}_page_{page_no}.png",
        )

    async def convert_note_to_pdf(
        self, user: str, file_id: int, page_no_list: list[int]
    ) -> None:
        """Convert a note to PDF and store it in CACHE_BUCKET."""
        user_id, node = await self._get_required_note_node(user, file_id)
        assert node.storage_key is not None and node.md5 is not None

        blob_content = await self.blob_storage.get_bytes(
            USER_DATA_BUCKET, node.storage_key
        )
        pdf_bytes = await asyncio.to_thread(
            _convert_note_to_pdf_sync, blob_content, page_no_list
        )
        pdf_storage_key = get_conversion_pdf_path(
            user_id=user_id,
            file_id=file_id,
            file_md5=node.md5,
            page_no_list=page_no_list,
        )
        await self.blob_storage.put(CACHE_BUCKET, pdf_storage_key, pdf_bytes)

    async def get_note_pdf(
        self, user: str, file_id: int, page_no_list: list[int] | None = None
    ) -> ConvertedBlob | None:
        """Resolve the CACHE_BUCKET blob and user-friendly filename for a converted note PDF."""
        resolved = await self._get_note_node_or_none(user, file_id)
        if not resolved:
            return None
        user_id, node = resolved
        if not node.md5:
            return None

        pdf_storage_key = get_conversion_pdf_path(
            user_id=user_id,
            file_id=file_id,
            file_md5=node.md5,
            page_no_list=page_no_list,
        )
        if not await self.blob_storage.exists(CACHE_BUCKET, pdf_storage_key):
            return None
        stem = Path(node.file_name).stem or f"note_{file_id}"
        return ConvertedBlob(
            storage_key=pdf_storage_key,
            file_name=f"{stem}.pdf",
        )

    async def _get_summary_handwriting_prefix(
        self, user: str, summary: SummaryItem
    ) -> str:
        """Resolve the CACHE_BUCKET key prefix for a summary's current handwriting version."""
        if summary.id is None or not summary.handwrite_inner_name:
            raise FileNotFound("Handwriting data not found")
        if not summary.handwrite_md5:
            raise FileError(f"Summary {summary.id} is missing handwriting MD5 hash")
        user_id = await self.user_service.get_user_id(user)
        try:
            return get_summary_handwriting_prefix(
                user_id, summary.id, summary.handwrite_md5
            )
        except ValueError as err:
            raise FileError(str(err)) from err

    async def _read_summary_handwriting(self, summary: SummaryItem) -> bytes:
        """Read a summary's raw handwriting `.mark` blob from USER_DATA_BUCKET."""
        assert summary.handwrite_inner_name is not None
        try:
            return await self.blob_storage.get_bytes(
                USER_DATA_BUCKET, summary.handwrite_inner_name
            )
        except FileNotFoundError as err:
            raise FileNotFound("Handwriting data not found") from err

    async def convert_summary_to_pdf(self, user: str, summary: SummaryItem) -> None:
        """Render a summary's handwriting to PDF and store it in CACHE_BUCKET."""
        prefix = await self._get_summary_handwriting_prefix(user, summary)
        storage_key = f"{prefix}.pdf"
        if await self.blob_storage.exists(CACHE_BUCKET, storage_key):
            return
        blob_content = await self._read_summary_handwriting(summary)
        pdf_bytes = await asyncio.to_thread(_convert_note_to_pdf_sync, blob_content, [])
        await self.blob_storage.put(CACHE_BUCKET, storage_key, pdf_bytes)

    async def get_summary_pdf(
        self, user: str, summary: SummaryItem
    ) -> ConvertedBlob | None:
        """Resolve the CACHE_BUCKET blob for a summary's current handwriting PDF."""
        prefix = await self._get_summary_handwriting_prefix(user, summary)
        storage_key = f"{prefix}.pdf"
        if not await self.blob_storage.exists(CACHE_BUCKET, storage_key):
            return None
        return ConvertedBlob(
            storage_key=storage_key, file_name=f"summary_{summary.id}.pdf"
        )

    async def convert_summary_to_png(
        self, user: str, summary: SummaryItem
    ) -> list[int]:
        """Render every page of a summary's handwriting to PNG in CACHE_BUCKET and return page numbers."""
        prefix = await self._get_summary_handwriting_prefix(user, summary)
        page_prefix = f"{prefix}_page_"
        cached_keys = await self.blob_storage.list_blobs(CACHE_BUCKET, page_prefix)
        if cached_keys:
            return sorted(
                int(key.removeprefix(page_prefix).removesuffix(".png"))
                for key in cached_keys
            )
        blob_content = await self._read_summary_handwriting(summary)
        pages = await asyncio.to_thread(_convert_note_to_png_pages_sync, blob_content)
        for page_no, png_bytes in enumerate(pages):
            await self.blob_storage.put(
                CACHE_BUCKET, f"{prefix}_page_{page_no}.png", png_bytes
            )
        return list(range(len(pages)))

    async def get_summary_png_page(
        self, user: str, summary: SummaryItem, page_no: int
    ) -> ConvertedBlob | None:
        """Resolve the CACHE_BUCKET blob for one page PNG of a summary's current handwriting."""
        prefix = await self._get_summary_handwriting_prefix(user, summary)
        storage_key = f"{prefix}_page_{page_no}.png"
        if not await self.blob_storage.exists(CACHE_BUCKET, storage_key):
            return None
        return ConvertedBlob(
            storage_key=storage_key,
            file_name=f"summary_{summary.id}_page_{page_no}.png",
        )

    async def _get_page_id(self, file_id: int, page_index: int) -> str | None:
        """Look up the `NotePageContentDO.page_id` for `(file_id, page_index)`."""
        async with self.session_manager.session() as session:
            stmt = select(NotePageContentDO.page_id).where(
                NotePageContentDO.file_id == file_id,
                NotePageContentDO.page_index == page_index,
            )
            page_id = (await session.execute(stmt)).scalar_one_or_none()
        return page_id or None

    async def _load_note_page_png(
        self,
        *,
        user_id: int,
        file_id: int,
        page_index: int,
    ) -> tuple[str, bytes] | None:
        """Resolve a `.note` page PNG from `CACHE_BUCKET`, rendering on demand on cache miss."""
        page_id = await self._get_page_id(file_id, page_index)
        if page_id is not None:
            png_key = get_page_png_path(file_id, page_id)
            try:
                return page_id, await self.blob_storage.get_bytes(
                    CACHE_BUCKET,
                    png_key,
                    max_bytes=MAX_SOURCE_IMAGE_BYTES,
                )
            except FileNotFoundError:
                pass

        rendered = await self.processor_service.process_file(
            file_id,
            user_id=user_id,
            task_types={TaskType.PAGE_HASHING, TaskType.PNG_CONVERSION},
            page_indices={page_index},
        )
        if not rendered:
            return None

        page_id = await self._get_page_id(file_id, page_index)
        if page_id is None:
            return None

        png_key = get_page_png_path(file_id, page_id)
        try:
            return page_id, await self.blob_storage.get_bytes(
                CACHE_BUCKET,
                png_key,
                max_bytes=MAX_SOURCE_IMAGE_BYTES,
            )
        except FileNotFoundError:
            return None

    async def _load_standalone_image_bytes(
        self,
        *,
        file_id: int,
        storage_key: str,
    ) -> tuple[str, bytes] | None:
        """Load cached PNG or raw standalone image bytes from blob storage."""
        cached_key = get_page_png_path(file_id, STANDALONE_IMAGE_PAGE_ID)
        try:
            return (
                STANDALONE_IMAGE_PAGE_ID,
                await self.blob_storage.get_bytes(
                    CACHE_BUCKET,
                    cached_key,
                    max_bytes=MAX_SOURCE_IMAGE_BYTES,
                ),
            )
        except FileNotFoundError:
            pass

        try:
            return (
                STANDALONE_IMAGE_PAGE_ID,
                await self.blob_storage.get_bytes(
                    USER_DATA_BUCKET,
                    storage_key,
                    max_bytes=MAX_SOURCE_IMAGE_BYTES,
                ),
            )
        except FileNotFoundError:
            return None

    async def get_page_image(
        self,
        *,
        user_id: int,
        file_id: int,
        page_index: int = 0,
        max_dimension: int = DEFAULT_MAX_IMAGE_DIMENSION,
    ) -> PageImage | None:
        """Return a normalized PNG `PageImage` for a `.note` page or standalone image.

        Returns `None` when the file or page is not accessible or does not exist.

        Raises:
            ValueError: If `page_index`, `max_dimension`, file type, or image size is invalid.
            FileError: If stored image bytes cannot be decoded.
        """
        if page_index < 0:
            raise ValueError(f"Invalid page_index '{page_index}': must be >= 0.")

        if (
            max_dimension < MIN_ALLOWED_IMAGE_DIMENSION
            or max_dimension > MAX_ALLOWED_IMAGE_DIMENSION
        ):
            raise ValueError(
                f"Invalid max_dimension '{max_dimension}': must be between "
                f"{MIN_ALLOWED_IMAGE_DIMENSION} and {MAX_ALLOWED_IMAGE_DIMENSION}."
            )

        async with self.session_manager.session() as session:
            stmt = select(UserFileDO).where(
                UserFileDO.id == file_id,
                UserFileDO.user_id == user_id,
                UserFileDO.is_active == "Y",
                UserFileDO.is_folder == "N",
            )
            file_do = (await session.execute(stmt)).scalar_one_or_none()

        if file_do is None or file_do.storage_key is None:
            return None

        is_note = file_do.file_name.lower().endswith(".note")
        is_image = is_image_filename(file_do.file_name)
        if not is_note and not is_image:
            raise ValueError(
                f"Unsupported file type for get_page_image: '{file_do.file_name}'."
            )

        if is_image and page_index != 0:
            return None

        if is_note:
            loaded = await self._load_note_page_png(
                user_id=user_id,
                file_id=file_id,
                page_index=page_index,
            )
        else:
            loaded = await self._load_standalone_image_bytes(
                file_id=file_id,
                storage_key=file_do.storage_key,
            )

        if loaded is None:
            return None

        page_id, raw_bytes = loaded
        try:
            png_bytes, width, height = await asyncio.to_thread(
                normalize_image_to_png,
                raw_bytes,
                max_dimension=max_dimension,
            )
        except ValueError as err:
            raise FileError(str(err)) from err

        return PageImage(
            file_name=file_do.file_name,
            page_index=page_index,
            page_id=page_id,
            png_bytes=png_bytes,
            width=width,
            height=height,
        )


CONVERSION_SERVICE_KEY: web.AppKey[ConversionService] = web.AppKey("conversion_service")
