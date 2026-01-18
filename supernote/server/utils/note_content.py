from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.note_processing import NotePageContentDO


async def get_page_content_by_id(
    session: AsyncSession, file_id: int, page_id: str
) -> Optional[NotePageContentDO]:
    """Retrieve NotePageContentDO by file_id and page_id using an existing session."""
    return (
        (
            await session.execute(
                select(NotePageContentDO)
                .where(NotePageContentDO.file_id == file_id)
                .where(NotePageContentDO.page_id == page_id)
            )
        )
        .scalars()
        .first()
    )
