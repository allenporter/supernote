"""Helpers for querying `NotePageContentDO`, inferring dates from `PAGEID`, and formatting page headers.

Provides `get_page_content_by_id`, `infer_page_date` (which extracts `YYYY-MM-DD` timestamps
embedded in Supernote `P<YYYYMMDDHHMMSS>...` page identifiers), and `format_page_metadata`
used by `supernote.server.ai.prompts`, `supernote.server.services.processor_modules.summary.SummaryModule`,
and `supernote.server.components.search.service.SearchService`.
"""

import re
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NotePageMetadataDO,
)

_DEVICE_STYLE_SUFFIX_RE = re.compile(r"_(?:a5x2|a5x|a6x2|a6x|n5|n6)$", re.IGNORECASE)


async def get_page_content_by_id(
    session: AsyncSession, file_id: int, page_id: str
) -> NotePageContentDO | None:
    """Retrieve NotePageContentDO by file_id and page_id using an existing session."""
    return (
        (
            await session.execute(
                select(NotePageContentDO)
                .options(undefer(NotePageContentDO.previous_text))
                .where(NotePageContentDO.file_id == file_id)
                .where(NotePageContentDO.page_id == page_id)
            )
        )
        .scalars()
        .first()
    )


async def get_page_keywords_map(
    session: AsyncSession,
    user_id: int,
    file_id: int,
) -> dict[str, list[str]]:
    """Return a map of `page_id -> keyword_texts` for a file's pages."""
    rows = (
        (
            await session.execute(
                select(NotePageMetadataDO).where(
                    NotePageMetadataDO.user_id == user_id,
                    NotePageMetadataDO.file_id == file_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        pm.page_id: pm.keyword_texts for pm in rows if pm.page_id and pm.keyword_texts
    }


def normalize_page_style_type(page_style: str | None) -> str | None:
    """Normalize a raw Supernote PAGESTYLE identifier into a canonical prompt slug.

    Examples:
        'user_Daily' -> 'daily'
        'style_h_8mm_ruled_line_a5x2' -> '8mm_ruled_line'
    """
    if not page_style:
        return None
    cleaned = page_style.strip()
    if not cleaned:
        return None

    lower = cleaned.lower()
    if lower.startswith("user_"):
        cleaned = cleaned[5:]
    elif lower.startswith("style_h_"):
        cleaned = cleaned[8:]
    elif lower.startswith("style_"):
        cleaned = cleaned[6:]

    cleaned = _DEVICE_STYLE_SUFFIX_RE.sub("", cleaned)
    slug = re.sub(r"[\s\-]+", "_", cleaned.strip(" _")).lower()
    return slug or None


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
    file_name: str | None = None,
    notebook_create_time: int | None = None,
    keywords: Sequence[str] | None = None,
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

    if keywords:
        cleaned_keywords = [kw.strip() for kw in keywords if kw and kw.strip()]
        if cleaned_keywords:
            lines.append(f"Page Keywords: {', '.join(cleaned_keywords)}")

    if include_section_divider:
        lines.append("---")

    return "\n".join(lines)
