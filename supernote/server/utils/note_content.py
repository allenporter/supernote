import re
from datetime import datetime
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


def infer_page_date(page_id: str) -> datetime | None:
    """Infers a date from a Supernote PAGEID string.

    PAGEID usually looks like: P20231027123456... (P followed by YYYYMMDDHHMMSS)
    """
    if not page_id or not page_id.startswith("P"):
        return None

    # Try to extract YYYYYMMDD
    match = re.match(r"P(\d{8})", page_id)
    if not match:
        return None

    date_str = match.group(1)
    try:
        return datetime.strptime(date_str, "%Y%m%d")
    except ValueError:
        return None


def format_page_metadata(
    page_index: int,
    page_id: str,
    file_name: Optional[str] = None,
    notebook_create_time: Optional[int] = None,
    include_section_divider: bool = False,
) -> str:
    """Formats a consistent metadata block for a notebook page.

    Used in OCR prompts, transcripts, and summaries.
    """
    lines = [f"--- Page {page_index + 1} ---"]
    if file_name:
        lines.append(f"Notebook Filename: {file_name}")

    if notebook_create_time:
        nb_dt = datetime.fromtimestamp(notebook_create_time / 1000)
        lines.append(f"Notebook Created: {nb_dt.strftime('%Y-%m-%d %H:%M:%S')}")

    lines.append(f"Page ID: {page_id}")

    inferred_date = infer_page_date(page_id)
    if inferred_date:
        lines.append(f"Page Date (Inferred): {inferred_date.strftime('%Y-%m-%d')}")

    if include_section_divider:
        lines.append("---")

    return "\n".join(lines)
