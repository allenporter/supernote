"""Pure text normalization, page timestamp inference, length formatting, and deep-link helpers."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from supernote.models.schedule import ScheduleTaskLinkDTO
from supernote.server.rapid_log.models import (
    MAX_TASK_DETAIL_LENGTH,
    MAX_TASK_TITLE_LENGTH,
    NOTE_APP_NAME,
    TaskImportance,
    TaskStatus,
)
from supernote.server.utils.rapid_log import RapidLogTaskState

__all__ = [
    "build_note_task_link",
    "clean_headline_text",
    "expected_importance",
    "expected_status",
    "field_values_differ",
    "format_migrated_detail",
    "format_task_title_and_detail",
    "infer_page_created_ms",
    "infer_page_date_ms",
    "merge_migrated_detail",
    "normalize_due_time",
    "normalize_rapid_log_text",
    "strip_overlong_headline_prefix",
]

_WHITESPACE_RE = re.compile(r"\s+")
_PAGE_CREATED_HMS_RE = re.compile(r"^P(\d{14})")
_PAGE_CREATED_DATE_RE = re.compile(r"^P(\d{8})")


def clean_headline_text(text: str) -> str:
    """Collapse internal whitespace and strip outer whitespace while preserving case."""
    return _WHITESPACE_RE.sub(" ", text.strip())


def normalize_rapid_log_text(text: str) -> str:
    """Normalize bullet text for idempotent matching across syncs and migrations."""
    return clean_headline_text(text).casefold()


def infer_page_date_ms(page_id: str) -> int | None:
    """Infer UTC start-of-day epoch milliseconds from a Supernote `P<YYYYMMDD>...` page ID."""
    if not page_id or not page_id.startswith("P"):
        return None
    match = _PAGE_CREATED_DATE_RE.match(page_id)
    if not match:
        return None
    try:
        dt = datetime.strptime(match.group(1), "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def infer_page_created_ms(page_id: str) -> int | None:
    """Infer UTC page creation epoch milliseconds from `P<YYYYMMDDHHMMSS>...` (or `P<YYYYMMDD>...`)."""
    if not page_id or not page_id.startswith("P"):
        return None
    hms_match = _PAGE_CREATED_HMS_RE.match(page_id)
    if hms_match:
        try:
            dt = datetime.strptime(hms_match.group(1), "%Y%m%d%H%M%S").replace(
                tzinfo=timezone.utc
            )
            return int(dt.timestamp() * 1000)
        except ValueError:
            pass
    return infer_page_date_ms(page_id)


def strip_overlong_headline_prefix(
    detail: str | None,
    text: str,
    *,
    max_title_length: int = MAX_TASK_TITLE_LENGTH,
) -> str:
    """Remove an auto-prepended overlong headline prefix from `detail`, returning sub-notes."""
    cleaned_detail = (detail or "").strip()
    cleaned_text = clean_headline_text(text)
    if len(cleaned_text) <= max_title_length or not cleaned_detail:
        return cleaned_detail
    if cleaned_detail == cleaned_text:
        return ""
    prefix = f"{cleaned_text}\n\n"
    if cleaned_detail.startswith(prefix):
        return cleaned_detail[len(prefix) :].strip()
    return cleaned_detail


def format_task_title_and_detail(
    text: str,
    detail: str | None,
    *,
    max_title_length: int = MAX_TASK_TITLE_LENGTH,
    max_detail_length: int = MAX_TASK_DETAIL_LENGTH,
) -> tuple[str, str]:
    """Format `(title, detail)` safely within `ScheduleService` length limits.

    If `text` exceeds `max_title_length`, truncates `title` with `…` and prepends
    the full untruncated `text` into `detail` so zero handwritten content is lost.
    """
    cleaned_text = clean_headline_text(text)
    raw_detail = strip_overlong_headline_prefix(
        detail, cleaned_text, max_title_length=max_title_length
    )

    if len(cleaned_text) <= max_title_length:
        title = cleaned_text
        combined_detail = raw_detail
    else:
        title = cleaned_text[: max_title_length - 1].rstrip() + "…"
        combined_detail = (
            f"{cleaned_text}\n\n{raw_detail}" if raw_detail else cleaned_text
        )

    if len(combined_detail) > max_detail_length:
        combined_detail = combined_detail[: max_detail_length - 1] + "…"

    return title, combined_detail


def _contains_line_sequence(haystack_lines: list[str], needle_lines: list[str]) -> bool:
    """Return True if `needle_lines` appears as a contiguous stripped-line sequence in `haystack_lines`."""
    if not needle_lines or len(needle_lines) > len(haystack_lines):
        return False
    span = len(needle_lines)
    return any(
        haystack_lines[i : i + span] == needle_lines
        for i in range(len(haystack_lines) - span + 1)
    )


def merge_migrated_detail(
    existing_detail: str | None,
    new_item_detail: str | None,
    *,
    max_detail_length: int = MAX_TASK_DETAIL_LENGTH,
) -> str:
    """Preserve prior context notes when migrating a task headline, deduplicating whole lines."""
    existing_clean = (existing_detail or "").strip()
    new_clean = (new_item_detail or "").strip()
    if not new_clean:
        return existing_clean
    if not existing_clean or new_clean == existing_clean:
        return new_clean

    existing_lines = [line.strip() for line in existing_clean.splitlines()]
    new_lines = [line.strip() for line in new_clean.splitlines()]
    if _contains_line_sequence(existing_lines, new_lines):
        return existing_clean
    if _contains_line_sequence(new_lines, existing_lines):
        return new_clean

    merged = f"{existing_clean}\n{new_clean}"
    if len(merged) > max_detail_length:
        merged = merged[: max_detail_length - 1] + "…"
    return merged


def format_migrated_detail(
    remote_detail: str | None,
    text: str,
    new_item_detail: str | None,
    *,
    max_title_length: int = MAX_TASK_TITLE_LENGTH,
    max_detail_length: int = MAX_TASK_DETAIL_LENGTH,
) -> str:
    """Merge migrated sub-notes without duplicating an auto-prepended overlong headline."""
    prior_subnotes = strip_overlong_headline_prefix(
        remote_detail, text, max_title_length=max_title_length
    )
    merged_subnotes = merge_migrated_detail(
        prior_subnotes, new_item_detail, max_detail_length=max_detail_length
    )
    _, formatted_detail = format_task_title_and_detail(
        text,
        merged_subnotes,
        max_title_length=max_title_length,
        max_detail_length=max_detail_length,
    )
    return formatted_detail


def build_note_task_link(
    *,
    file_id: int,
    file_path: str,
    page_index: int,
    page_id: str,
    task_title: str,
) -> str:
    """Encode a Base64 `ScheduleTaskLinkDTO` deep-link to a 1-indexed `.note` page."""
    return ScheduleTaskLinkDTO(
        app_name=NOTE_APP_NAME,
        path=file_path,
        page=page_index + 1,
        file_id=str(file_id),
        page_id=page_id,
        task_title=task_title,
    ).to_b64()


def normalize_due_time(due_time: int | None) -> int | None:
    """Normalize `0` and `None` as unset due time."""
    return due_time if due_time else None


def expected_importance(is_starred: bool) -> str:
    """Return expected task importance for a starred/unstarred bullet."""
    return TaskImportance.HIGH if is_starred else TaskImportance.NORMAL


def expected_status(task_state: RapidLogTaskState | None) -> str:
    """Return expected `ScheduleTask` status string for a `RapidLogTaskState`."""
    return (
        TaskStatus.COMPLETED
        if task_state == RapidLogTaskState.COMPLETED
        else TaskStatus.NEEDS_ACTION
    )


def field_values_differ(field_name: str, a: Any, b: Any) -> bool:
    """Compare two `ScheduleTask` field values accounting for nullable/zero conventions."""
    if field_name == "due_time":
        return normalize_due_time(a) != normalize_due_time(b)
    if field_name == "detail":
        return (a or "") != (b or "")
    return bool(a != b)
