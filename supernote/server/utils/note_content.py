import json
import re
from datetime import datetime

from mashumaro.exceptions import InvalidFieldValue, MissingField
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.extended import (
    NoteKeywordVO,
    NoteLinkVO,
    NoteRectVO,
    NoteTitleVO,
)
from supernote.notebook import Keyword, Link, Title
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NotePageMetadataDO,
)


async def get_page_content_by_id(
    session: AsyncSession, file_id: int, page_id: str
) -> NotePageContentDO | None:
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


async def get_page_metadata_for_page(
    session: AsyncSession,
    file_id: int,
    page_id: str | None = None,
    page_index: int | None = None,
) -> NotePageMetadataDO | None:
    """Retrieve NotePageMetadataDO for a page by page_id (preferred) or page_index."""
    if page_id:
        by_id = (
            (
                await session.execute(
                    select(NotePageMetadataDO)
                    .where(NotePageMetadataDO.file_id == file_id)
                    .where(NotePageMetadataDO.page_id == page_id)
                )
            )
            .scalars()
            .first()
        )
        if by_id is not None:
            return by_id
    if page_index is not None:
        return (
            (
                await session.execute(
                    select(NotePageMetadataDO)
                    .where(NotePageMetadataDO.file_id == file_id)
                    .where(NotePageMetadataDO.page_index == page_index)
                )
            )
            .scalars()
            .first()
        )
    return None


def rect_to_vo(bbox: tuple[int, int, int, int] | None) -> NoteRectVO | None:
    """Convert a (left, top, right, bottom) tuple into a NoteRectVO."""
    if bbox is None:
        return None
    left, top, right, bottom = bbox
    return NoteRectVO(left=left, top=top, right=right, bottom=bottom)


def keyword_to_vo(kw: Keyword) -> NoteKeywordVO:
    """Convert a notebook Keyword domain object into a NoteKeywordVO."""
    bbox = kw.rect if kw.metadata.rect is not None else None
    return NoteKeywordVO(
        page_number=kw.page_number,
        text=kw.keyword or "",
        rect=rect_to_vo(bbox),
    )


def title_to_vo(title: Title) -> NoteTitleVO:
    """Convert a notebook Title domain object into a NoteTitleVO."""
    bbox = title.rect if title.metadata.rect is not None else None
    return NoteTitleVO(
        page_number=title.page_number,
        level=title.level,
        style=title.style,
        rect=rect_to_vo(bbox),
    )


def link_to_vo(link: Link) -> NoteLinkVO:
    """Convert a notebook Link domain object into a NoteLinkVO."""
    bbox = link.rect if link.metadata.rect is not None else None
    return NoteLinkVO(
        page_number=link.page_number,
        link_type=int(link.link_type),
        direction=int(link.direction),
        style=link.metadata.style,
        target=link.target,
        target_file_id=link.file_id,
        target_page_id=link.page_id,
        target_page_number=link.metadata.obj_page,
        rect=rect_to_vo(bbox),
    )


def parse_keywords_json(keywords_json: str | None) -> list[NoteKeywordVO]:
    """Deserialize a JSON array of NoteKeywordVO dicts safely."""
    if not keywords_json:
        return []
    try:
        raw = json.loads(keywords_json)
        if not isinstance(raw, list):
            return []
        return [NoteKeywordVO.from_dict(item) for item in raw if isinstance(item, dict)]
    except (
        json.JSONDecodeError,
        ValueError,
        TypeError,
        KeyError,
        MissingField,
        InvalidFieldValue,
    ):
        return []


def parse_titles_json(titles_json: str | None) -> list[NoteTitleVO]:
    """Deserialize a JSON array of NoteTitleVO dicts safely."""
    if not titles_json:
        return []
    try:
        raw = json.loads(titles_json)
        if not isinstance(raw, list):
            return []
        return [NoteTitleVO.from_dict(item) for item in raw if isinstance(item, dict)]
    except (
        json.JSONDecodeError,
        ValueError,
        TypeError,
        KeyError,
        MissingField,
        InvalidFieldValue,
    ):
        return []


def parse_links_json(links_json: str | None) -> list[NoteLinkVO]:
    """Deserialize a JSON array of NoteLinkVO dicts safely."""
    if not links_json:
        return []
    try:
        raw = json.loads(links_json)
        if not isinstance(raw, list):
            return []
        return [NoteLinkVO.from_dict(item) for item in raw if isinstance(item, dict)]
    except (
        json.JSONDecodeError,
        ValueError,
        TypeError,
        KeyError,
        MissingField,
        InvalidFieldValue,
    ):
        return []


def extract_page_keyword_texts(keywords_json: str | None) -> list[str]:
    """Extract non-empty keyword strings from a persisted page keywords_json column."""
    return [
        kw.text.strip()
        for kw in parse_keywords_json(keywords_json)
        if kw.text and kw.text.strip()
    ]


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


_DEVICE_STYLE_SUFFIX_RE = re.compile(r"_(?:a5x2|a5x|a6x2|a6x|n5|n6)$", re.IGNORECASE)


def normalize_page_style_type(page_style: str | None) -> str | None:
    """Normalize a raw Supernote PAGESTYLE identifier into a canonical slug.

    Examples:
        'style_four_quadrant_method' -> 'four_quadrant_method'
        'style_h_8mm_ruled_line_a5x2' -> '8mm_ruled_line'
        'user_Daily' -> 'daily'
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


def format_page_style(page_style: str | None) -> str | None:
    """Format a raw Supernote PAGESTYLE string into a human-readable label."""
    if not page_style:
        return None
    cleaned = page_style.strip()
    if not cleaned:
        return None

    if cleaned.lower().startswith("user_"):
        raw_name = _DEVICE_STYLE_SUFFIX_RE.sub("", cleaned[5:]).strip(" _-")
        if not raw_name:
            return "Custom Template"
        words = [
            w if any(ch.isupper() for ch in w[1:]) else w.capitalize()
            for w in re.split(r"[_\s]+", raw_name)
            if w
        ]
        return f"Custom: {' '.join(words)}"

    slug = normalize_page_style_type(cleaned)
    if not slug:
        return None
    if slug == "white":
        return "Blank Canvas"

    words = [
        token if re.match(r"^\d+mm$", token) else token.capitalize()
        for token in slug.split("_")
        if token
    ]
    return " ".join(words) if words else None


def format_page_metadata(
    page_index: int,
    page_id: str,
    file_name: str | None = None,
    notebook_create_time: int | None = None,
    page_style: str | None = None,
    keywords: list[str] | None = None,
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

    formatted_style = format_page_style(page_style)
    if formatted_style:
        lines.append(f"Page Style: {formatted_style}")

    if keywords:
        cleaned_keywords = [kw.strip() for kw in keywords if kw and kw.strip()]
        if cleaned_keywords:
            lines.append(f"Page Keywords: {', '.join(cleaned_keywords)}")

    if include_section_divider:
        lines.append("---")

    return "\n".join(lines)
