"""Read service for persisted `.note` structural metadata and title crop PNGs."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging

from aiohttp import web
from sqlalchemy import and_, select

from supernote.models.extended import (
    NoteLinkVO,
    NotePageMetadataVO,
    NoteTitleVO,
    WebNoteMetadataVO,
)
from supernote.notebook import exceptions as notebook_exceptions
from supernote.notebook.converter import ImageConverter
from supernote.notebook.fileformat import Notebook
from supernote.notebook.parser import load_title_bitmaps, parse_metadata
from supernote.notebook.schema import (
    LinkDirection,
    LinkType,
    PageMetadata,
    SupernoteMetadata,
)
from supernote.server.constants import CACHE_BUCKET, USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NoteMetadataDO,
    NotePageMetadataDO,
    NoteTitleDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.utils.note_content import (
    infer_page_date,
    normalize_page_style_type,
)
from supernote.server.utils.paths import get_title_png_path

__all__ = [
    "NOTE_METADATA_SERVICE_KEY",
    "NoteMetadataService",
]

logger = logging.getLogger(__name__)


def _render_title_pngs(path: str) -> dict[str, bytes]:
    """Render every decodable title crop of a note in one parse, keyed by `<TITLEBITMAP>` MD5."""
    with open(path, "rb") as stream:
        notebook = Notebook(parse_metadata(stream, policy="loose"))
        load_title_bitmaps(stream, notebook.titles)
    converter = ImageConverter(notebook)
    pngs: dict[str, bytes] = {}
    for title in notebook.titles:
        if not title.content:
            continue
        md5 = hashlib.md5(title.content).hexdigest()
        try:
            buf = io.BytesIO()
            converter.convert_title(title).save(buf, format="PNG")
        except (
            notebook_exceptions.SupernoteLibException,
            IndexError,
            ValueError,
        ) as err:
            logger.warning(
                f"Failed to render title crop {md5} on page {title.page_number}: {err}"
            )
            continue
        pngs[md5] = buf.getvalue()
    return pngs


class NoteMetadataService:
    """Queries persisted `.note` structural metadata and caches on-demand title crop PNGs."""

    def __init__(
        self,
        session_manager: DatabaseSessionManager,
        blob_storage: BlobStorage,
    ) -> None:
        self.session_manager = session_manager
        self.blob_storage = blob_storage

    async def get_note_metadata(
        self,
        user_id: int,
        file_id: int,
    ) -> WebNoteMetadataVO | None:
        """Return structured notebook and per-page metadata for an active `.note` file owned by `user_id`."""
        async with self.session_manager.session() as session:
            file_row = (
                await session.execute(
                    select(UserFileDO).where(
                        UserFileDO.id == file_id,
                        UserFileDO.user_id == user_id,
                        UserFileDO.is_active == "Y",
                    )
                )
            ).scalar_one_or_none()
            if file_row is None:
                return None

            meta_do = await session.get(NoteMetadataDO, (user_id, file_id))
            if meta_do is None:
                return None

            page_rows = list(
                (
                    await session.execute(
                        select(NotePageMetadataDO)
                        .where(
                            NotePageMetadataDO.user_id == user_id,
                            NotePageMetadataDO.file_id == file_id,
                        )
                        .order_by(NotePageMetadataDO.page_index)
                    )
                )
                .scalars()
                .all()
            )
            title_rows = list(
                (
                    await session.execute(
                        select(NoteTitleDO)
                        .where(
                            NoteTitleDO.user_id == user_id,
                            NoteTitleDO.file_id == file_id,
                        )
                        .order_by(NoteTitleDO.title_index)
                    )
                )
                .scalars()
                .all()
            )

            header_dict = json.loads(meta_do.header_json)
            footer_dict = json.loads(meta_do.footer_json)
            if not isinstance(header_dict, dict) or not isinstance(footer_dict, dict):
                raise ValueError("header_json and footer_json must be JSON objects")
            notebook = Notebook(
                SupernoteMetadata(
                    type=meta_do.file_type or "note",
                    signature=meta_do.signature or "",
                    header=header_dict,
                    footer=footer_dict,
                    pages=[],
                )
            )

            outgoing_links = [
                lk for lk in notebook.links if lk.direction == LinkDirection.OUT
            ]
            external_native_ids = {
                lk.file_id
                for lk in outgoing_links
                if lk.file_id and lk.file_id != meta_do.native_file_id
            }
            native_to_file_id: dict[str, int] = {}
            if external_native_ids:
                ext_file_rows = (
                    await session.execute(
                        select(NoteMetadataDO.native_file_id, NoteMetadataDO.file_id)
                        .join(
                            UserFileDO,
                            (UserFileDO.id == NoteMetadataDO.file_id)
                            & (UserFileDO.user_id == NoteMetadataDO.user_id),
                        )
                        .where(
                            NoteMetadataDO.user_id == user_id,
                            NoteMetadataDO.native_file_id.in_(external_native_ids),
                            UserFileDO.is_active == "Y",
                        )
                    )
                ).all()
                for native_id, resolved_fid in ext_file_rows:
                    if native_id:
                        native_to_file_id[native_id] = resolved_fid

            page_index_by_target: dict[tuple[int, str], int] = {
                (file_id, pm.page_id): pm.page_index for pm in page_rows if pm.page_id
            }
            external_page_ids = {
                lk.page_id
                for lk in outgoing_links
                if lk.page_id and lk.file_id and lk.file_id in native_to_file_id
            }
            if external_page_ids and native_to_file_id:
                ext_page_rows = (
                    await session.execute(
                        select(
                            NotePageMetadataDO.file_id,
                            NotePageMetadataDO.page_id,
                            NotePageMetadataDO.page_index,
                        ).where(
                            NotePageMetadataDO.user_id == user_id,
                            NotePageMetadataDO.file_id.in_(native_to_file_id.values()),
                            NotePageMetadataDO.page_id.in_(external_page_ids),
                        )
                    )
                ).all()
                for ext_fid, ext_pid, ext_idx in ext_page_rows:
                    page_index_by_target[(ext_fid, ext_pid)] = ext_idx

        page_vos: list[NotePageMetadataVO] = []
        for pm in page_rows:
            has_five_star = False
            try:
                raw_page = json.loads(pm.page_json)
                if isinstance(raw_page, dict):
                    has_five_star = bool(PageMetadata.from_params(raw_page).five_star)
            except (
                json.JSONDecodeError,
                ValueError,
                TypeError,
                notebook_exceptions.ParserException,
            ) as err:
                logger.warning(
                    f"Failed to deserialize page_json for file {file_id} page {pm.page_index}: {err}"
                )

            inferred_dt = infer_page_date(pm.page_id)
            page_vos.append(
                NotePageMetadataVO(
                    page_index=pm.page_index,
                    page_id=pm.page_id,
                    date=inferred_dt.strftime("%Y-%m-%d") if inferred_dt else None,
                    style=normalize_page_style_type(pm.page_style),
                    is_blank=not pm.has_drawables,
                    has_five_star=has_five_star,
                    keywords=pm.keyword_texts,
                )
            )

        keywords_by_text: dict[str, list[int]] = {}
        for kw in notebook.keywords:
            if kw.keyword and kw.keyword.strip():
                text = kw.keyword.strip()
                indices = keywords_by_text.setdefault(text, [])
                if kw.page_number not in indices:
                    indices.append(kw.page_number)

        link_vos: list[NoteLinkVO] = []
        for lk in outgoing_links:
            link_type_name = (
                lk.link_type.name.lower()
                if isinstance(lk.link_type, LinkType)
                else str(lk.link_type)
            )
            if not lk.file_id or lk.file_id == meta_do.native_file_id:
                resolved_file_id: int | None = file_id if lk.page_id else None
            else:
                resolved_file_id = native_to_file_id.get(lk.file_id)

            target_page_index: int | None = None
            if lk.page_id and resolved_file_id is not None:
                target_page_index = page_index_by_target.get(
                    (resolved_file_id, lk.page_id)
                )
            if (
                target_page_index is None
                and lk.metadata.obj_page
                and lk.metadata.obj_page > 0
            ):
                target_page_index = lk.metadata.obj_page - 1

            link_vos.append(
                NoteLinkVO(
                    page_index=lk.page_number,
                    link_type=link_type_name,
                    target=lk.target,
                    target_file_id=(
                        resolved_file_id if resolved_file_id != file_id else None
                    ),
                    target_page_index=target_page_index,
                )
            )

        equipment = (
            str(notebook.metadata.header.apply_equipment)
            if notebook.metadata.header.apply_equipment
            else None
        )
        return WebNoteMetadataVO(
            file_id=file_id,
            equipment=equipment,
            total_pages=meta_do.total_pages,
            keywords=keywords_by_text,
            titles=[
                NoteTitleVO(
                    page_index=t.page_index,
                    level=t.level,
                    style=t.style,
                    rect=t.rect,
                    bitmap_md5=t.bitmap_md5,
                )
                for t in title_rows
            ],
            links=link_vos,
            pages=page_vos,
        )

    async def get_title_png_key(
        self, *, user_id: int, file_id: int, bitmap_md5: str
    ) -> str | None:
        """Return the `CACHE_BUCKET` key of a title crop PNG, rendering it on a cache miss.

        Returns `None` unless `user_id` owns the active note and one of its
        persisted titles has this `bitmap_md5`, or if the note no longer contains
        that bitmap or its crop cannot be decoded.
        """
        async with self.session_manager.session() as session:
            storage_key = (
                await session.execute(
                    select(UserFileDO.storage_key)
                    .join(
                        NoteTitleDO,
                        and_(
                            NoteTitleDO.user_id == UserFileDO.user_id,
                            NoteTitleDO.file_id == UserFileDO.id,
                        ),
                    )
                    .where(
                        UserFileDO.id == file_id,
                        UserFileDO.user_id == user_id,
                        UserFileDO.is_active == "Y",
                        NoteTitleDO.bitmap_md5 == bitmap_md5,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
        if not storage_key:
            return None

        png_key = get_title_png_path(file_id, bitmap_md5)
        if await self.blob_storage.exists(CACHE_BUCKET, png_key):
            return png_key

        # A cache miss usually means the whole outline is uncached, so render and
        # store every crop from one parse instead of re-parsing per title.
        path = self.blob_storage.get_blob_path(USER_DATA_BUCKET, storage_key)
        try:
            pngs = await asyncio.to_thread(_render_title_pngs, str(path))
        except (notebook_exceptions.SupernoteLibException, FileNotFoundError) as err:
            logger.warning(f"Failed to render titles of file {file_id}: {err}")
            return None
        for md5, png_bytes in pngs.items():
            await self.blob_storage.put(
                CACHE_BUCKET, get_title_png_path(file_id, md5), png_bytes
            )
        return png_key if bitmap_md5 in pngs else None


NOTE_METADATA_SERVICE_KEY: web.AppKey[NoteMetadataService] = web.AppKey(
    "note_metadata_service"
)
