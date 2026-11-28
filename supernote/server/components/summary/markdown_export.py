"""Markdown exporter for Supernote Digests (`GET /api/extended/digests/export`)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from supernote.models.extended import DigestVO

__all__ = ["format_digests_markdown"]

_WHITESPACE_RUN = re.compile(r"[\r\n]+")


def _single_line(text: str) -> str:
    """Collapse embedded newlines so headings and inline labels stay single-line."""
    return _WHITESPACE_RUN.sub(" ", text).strip()


def _code_span(text: str) -> str:
    """Wrap `text` in a safe Markdown inline code span even if it contains backticks."""
    cleaned = _single_line(text)
    longest = max((len(m.group(0)) for m in re.finditer(r"`+", cleaned)), default=0)
    fence = "`" * (longest + 1)
    if cleaned.startswith("`") or cleaned.endswith("`"):
        return f"{fence} {cleaned} {fence}"
    return f"{fence}{cleaned}{fence}"


def _format_iso_date(epoch_ms: int | None) -> str | None:
    """Format an epoch-millisecond timestamp as `YYYY-MM-DD` (UTC), or `None`."""
    if not epoch_ms or epoch_ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(epoch_ms / 1000, tz=UTC).strftime("%Y-%m-%d")
    except (ValueError, OverflowError, OSError):
        return None


def _source_group_key(source_path: str | None) -> str:
    """Normalize a VFS source path for grouping, or empty string for standalone digests."""
    if not source_path:
        return ""
    return _single_line(source_path).lstrip("/")


def _source_label(source_path: str) -> str:
    """Extract a concise display title from a normalized source path."""
    if not source_path:
        return "Standalone Digests"
    return _single_line(Path(source_path).name or source_path)


def _format_single_digest(digest: DigestVO) -> str:
    """Format a single `DigestVO` as a Markdown section."""
    parts: list[str] = []
    if digest.content and (content := digest.content.strip()):
        parts.append(content)
    if digest.comment and (comment := digest.comment.strip()):
        quoted = "\n".join(
            f"> {line}" if line else ">" for line in comment.splitlines()
        )
        parts.append(quoted)
    if (
        digest.handwriting is not None
        and digest.handwriting.transcript
        and (transcript := digest.handwriting.transcript.strip())
    ):
        parts.append(f"**Handwritten annotation:**\n\n{transcript}")

    meta_parts: list[str] = []
    if digest.author and (author := _single_line(digest.author)):
        meta_parts.append(author)
    if digest.tags:
        tags_str = " ".join(f"#{tag.strip()}" for tag in digest.tags if tag.strip())
        if tags_str:
            meta_parts.append(tags_str)
    if date_str := _format_iso_date(digest.update_time or digest.creation_time):
        meta_parts.append(date_str)
    if meta_parts:
        parts.append(f"_{' · '.join(meta_parts)}_")

    return "\n\n".join(parts)


def format_digests_markdown(
    digests: Sequence[DigestVO],
    *,
    title: str = "Digests",
) -> str:
    """Render a sequence of `DigestVO` records as grouped, PKM-ready Markdown."""
    heading = _single_line(title) or "Digests"
    if not digests:
        return f"# {heading}\n\n_No digests found._\n"

    groups: dict[str, list[DigestVO]] = {}
    for digest in digests:
        key = _source_group_key(digest.source_path)
        groups.setdefault(key, []).append(digest)

    sections: list[str] = [f"# {heading}"]
    for source_path, items in groups.items():
        formatted_items = [
            rendered for item in items if (rendered := _format_single_digest(item))
        ]
        if not formatted_items:
            continue
        group_lines: list[str] = [f"## {_source_label(source_path)}"]
        if source_path:
            group_lines.append(f"Source: {_code_span(source_path)}")
        group_lines.append("\n\n---\n\n".join(formatted_items))
        sections.append("\n\n".join(group_lines))

    if len(sections) == 1:
        return f"# {heading}\n\n_No digests found._\n"

    return "\n\n".join(sections) + "\n"
