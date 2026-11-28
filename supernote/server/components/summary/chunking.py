"""Pure page-chunking, rolling-context, and segment-merging helpers for `SummaryModule`.

All functions in this module are transport- and database-free so notebook
partitioning, incremental cache fingerprinting, and cross-chunk segment
stitching can be unit-tested deterministically.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from supernote.models.summary import METADATA_CHUNKS
from supernote.server.ai.prompts import SummarySegment

__all__ = [
    "CHUNK_CACHE_VERSION",
    "FormattedPage",
    "PageChunk",
    "compute_chunk_hash",
    "format_prior_context",
    "merge_chunk_segments",
    "normalize_segments",
    "parse_cached_chunks",
    "partition_pages",
    "render_segments_markdown",
]

CHUNK_CACHE_VERSION = "v1"
_DATE_LOOKBACK_LIMIT = 3


@dataclass(frozen=True)
class FormattedPage:
    """One non-blank notebook page formatted with metadata and OCR text."""

    page_index: int
    page_id: str
    page_date: str | None
    formatted_text: str


@dataclass(frozen=True)
class PageChunk:
    """An ordered slice of formatted notebook pages sent to one LLM summary call."""

    pages: tuple[FormattedPage, ...]

    @property
    def transcript(self) -> str:
        return "\n\n".join(p.formatted_text for p in self.pages)

    @property
    def char_count(self) -> int:
        if not self.pages:
            return 0
        return sum(len(p.formatted_text) for p in self.pages) + 2 * (
            len(self.pages) - 1
        )


def _find_date_split_index(
    current: list[FormattedPage], next_page: FormattedPage
) -> int | None:
    """Find an earlier index in `current` to keep `next_page.page_date` unbroken."""
    if not next_page.page_date or len(current) <= 1:
        return None
    if current[-1].page_date != next_page.page_date:
        return None
    lookback_floor = max(1, len(current) - _DATE_LOOKBACK_LIMIT)
    idx = len(current) - 1
    while idx > lookback_floor and current[idx - 1].page_date == next_page.page_date:
        idx -= 1
    if current[idx - 1].page_date != next_page.page_date:
        return idx
    return None


def partition_pages(
    pages: Sequence[FormattedPage],
    *,
    max_pages_per_chunk: int,
    max_chars_per_chunk: int,
) -> list[PageChunk]:
    """Partition ordered non-blank pages into bounded, date-aware `PageChunk`s.

    When `max_pages_per_chunk == 0`, chunking is disabled and all pages are
    returned as a single chunk.
    """
    if not pages:
        return []
    if max_pages_per_chunk == 0:
        return [PageChunk(tuple(pages))]

    chunks: list[PageChunk] = []
    current: list[FormattedPage] = []
    current_chars = 0

    for page in pages:
        page_len = len(page.formatted_text)
        added_chars = page_len if not current else page_len + 2
        exceeds_pages = len(current) >= max_pages_per_chunk
        exceeds_chars = bool(current) and (
            current_chars + added_chars > max_chars_per_chunk
        )

        if current and (exceeds_pages or exceeds_chars):
            split_idx = _find_date_split_index(current, page)
            if split_idx is not None:
                chunks.append(PageChunk(tuple(current[:split_idx])))
                carried = current[split_idx:]
                current = [*carried, page]
                current_chars = sum(len(p.formatted_text) for p in current) + 2 * (
                    len(current) - 1
                )
            else:
                chunks.append(PageChunk(tuple(current)))
                current = [page]
                current_chars = page_len
        else:
            current.append(page)
            current_chars += added_chars

    if current:
        chunks.append(PageChunk(tuple(current)))

    return chunks


def compute_chunk_hash(
    chunk: PageChunk,
    *,
    model_id: str,
    custom_type: str,
    prior_context: str | None = None,
) -> str:
    """Compute a deterministic cache fingerprint for one `PageChunk`."""
    payload = {
        "v": CHUNK_CACHE_VERSION,
        "model_id": model_id,
        "custom_type": custom_type,
        "prior_context": prior_context or "",
        "pages": [[p.page_index, p.page_id, p.formatted_text] for p in chunk.pages],
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def normalize_segments(segments: Sequence[SummarySegment]) -> list[dict[str, Any]]:
    """Convert `SummarySegment` dataclasses into normalized metadata dicts."""
    cleaned: list[dict[str, Any]] = []
    for seg in segments:
        date_range = (seg.date_range or "").strip() or "Unknown Date"
        text = (seg.summary or "").replace("\\n", "\n").strip()
        dates = [str(d) for d in (seg.extracted_dates or []) if str(d).strip()]
        page_refs = [int(p) for p in (seg.page_refs or [])]
        cleaned.append(
            {
                "date_range": date_range,
                "summary": text,
                "extracted_dates": dates,
                "page_refs": page_refs,
            }
        )
    return cleaned


def format_prior_context(
    segments: Sequence[dict[str, Any]],
    *,
    max_segments: int = 2,
    max_chars: int = 1200,
) -> str | None:
    """Format the trailing segments of the prior chunk as bounded rolling context."""
    if not segments:
        return None
    tail = segments[-max(1, max_segments) :]
    parts: list[str] = []
    for seg in tail:
        date_range = str(seg.get("date_range") or "Unknown Date")
        page_refs = seg.get("page_refs") or []
        header = f"## {date_range}"
        if page_refs:
            pages_str = ", ".join(str(p) for p in page_refs)
            header += f" (Pages {pages_str})"
        summary = str(seg.get("summary") or "").strip()
        parts.append(f"{header}\n{summary}" if summary else header)
    joined = "\n\n".join(parts).strip()
    if not joined:
        return None
    if len(joined) > max_chars:
        return joined[: max_chars - 3].rstrip() + "..."
    return joined


def merge_chunk_segments(
    chunk_segment_lists: Sequence[Sequence[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Stitch ordered chunk segments, merging adjacent entries with identical `date_range`."""
    merged: list[dict[str, Any]] = []
    for seg_list in chunk_segment_lists:
        for seg in seg_list:
            date_range = (
                str(seg.get("date_range") or "Unknown Date").strip() or "Unknown Date"
            )
            summary = str(seg.get("summary") or "").strip()
            extracted_dates = [
                str(d) for d in (seg.get("extracted_dates") or []) if str(d).strip()
            ]
            page_refs = [int(p) for p in (seg.get("page_refs") or [])]

            norm_key = date_range.lower()
            if (
                merged
                and norm_key != "unknown date"
                and str(merged[-1]["date_range"]).strip().lower() == norm_key
            ):
                prev = merged[-1]
                prev_summary = str(prev["summary"]).strip()
                if summary and summary != prev_summary:
                    prev["summary"] = (
                        f"{prev_summary}\n{summary}" if prev_summary else summary
                    )
                prev["extracted_dates"] = list(
                    dict.fromkeys([*prev["extracted_dates"], *extracted_dates])
                )
                prev["page_refs"] = sorted({*prev["page_refs"], *page_refs})
            else:
                merged.append(
                    {
                        "date_range": date_range,
                        "summary": summary,
                        "extracted_dates": list(dict.fromkeys(extracted_dates)),
                        "page_refs": sorted(set(page_refs)),
                    }
                )
    return merged


def render_segments_markdown(segments: Sequence[dict[str, Any]]) -> str:
    """Render normalized summary segments into the Digest Markdown body."""
    parts: list[str] = []
    for seg in segments:
        date_range = str(seg.get("date_range") or "Unknown Date")
        text = str(seg.get("summary") or "")
        page_refs = seg.get("page_refs") or []
        header = f"## {date_range}"
        if page_refs:
            pages_str = ", ".join(str(p) for p in page_refs)
            header += f" (Pages {pages_str})"
        parts.append(f"{header}\n{text}")
    return "\n\n".join(parts) if parts else "No summary generated."


def parse_cached_chunks(metadata_str: str | None) -> dict[str, list[dict[str, Any]]]:
    """Extract `{chunk_hash: segments}` from existing `SummaryDO.extra_metadata` JSON."""
    if not metadata_str:
        return {}
    try:
        meta = json.loads(metadata_str)
    except (ValueError, TypeError):
        return {}
    if not isinstance(meta, dict):
        return {}
    raw_chunks = meta.get(METADATA_CHUNKS)
    if not isinstance(raw_chunks, list):
        return {}
    cache: dict[str, list[dict[str, Any]]] = {}
    for entry in raw_chunks:
        if not isinstance(entry, dict):
            continue
        chunk_hash = entry.get("chunk_hash")
        segments = entry.get("segments")
        if isinstance(chunk_hash, str) and chunk_hash and isinstance(segments, list):
            cache[chunk_hash] = [seg for seg in segments if isinstance(seg, dict)]
    return cache
