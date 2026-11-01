import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.note_processing import NotePageContentDO


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

    is_custom = cleaned.lower().startswith("user_")
    if is_custom:
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

    words = []
    for token in slug.split("_"):
        if not token:
            continue
        if re.match(r"^\d+mm$", token):
            words.append(token)
        else:
            words.append(token.capitalize())
    return " ".join(words) if words else None


def format_page_metadata(
    page_index: int,
    page_id: str,
    file_name: str | None = None,
    notebook_create_time: int | None = None,
    page_style: str | None = None,
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

    if include_section_divider:
        lines.append("---")

    return "\n".join(lines)
