"""Parser for extracting Bullet Journal rapid-logging tasks and checkboxes from OCR text."""

import re
from dataclasses import dataclass
from enum import Enum

__all__ = [
    "ExtractedPageTask",
    "ExtractedTaskState",
    "normalize_task_title",
    "parse_page_tasks",
]


class ExtractedTaskState(str, Enum):
    """Handwritten task state extracted from OCR rapid-logging notation."""

    INCOMPLETE = "INCOMPLETE"
    COMPLETED = "COMPLETED"
    MIGRATED_FORWARD = "MIGRATED_FORWARD"
    MIGRATED_SCHEDULED = "MIGRATED_SCHEDULED"
    CANCELLED = "CANCELLED"


@dataclass(slots=True)
class ExtractedPageTask:
    """Structured representation of a task extracted from a notebook page."""

    raw_title: str
    normalized_title: str
    state: ExtractedTaskState
    is_starred: bool = False
    detail: str | None = None
    line_number: int = 0


# Matches whitespace runs
_WHITESPACE_RE = re.compile(r"\s+")
# Trailing punctuation that OCR may inconsistently include or omit
_TRAILING_PUNCT_RE = re.compile(r"[.;,:]+$")

# Matches inner signifiers inside strikethrough text, e.g. "~~* • Call Bob~~" -> "Call Bob"
_INNER_SIGNIFIER_RE = re.compile(
    r"^(?:\*\s+)?(?:[•X><]|-\s*\[[ xX]\]|\[[ xX]\])\s+(?P<title>.+)$"
)

# Full-line strikethrough: "~~...~~" or "* ~~...~~"
_FULL_STRIKETHROUGH_RE = re.compile(r"^(?P<star>\*\s+)?~~\s*(?P<inner>.+?)\s*~~\s*$")

# Task signifier followed by strikethrough title: "• ~~Call Bob~~" or "* • ~~Call Bob~~"
_SIGNIFIER_STRIKETHROUGH_RE = re.compile(
    r"^(?P<star>\*\s+)?(?:[•X><]|-\s*\[[ xX]\]|\[[ xX]\])\s+~~\s*(?P<title>.+?)\s*~~\s*$"
)

# Active task line patterns (unindented):
# Supports optional "* " critical signifier followed by:
#   - "• " (incomplete rapid-logging task)
#   - "- [ ] " or "[ ] " (incomplete checkbox)
#   - "X " or "- [x] " or "- [X] " or "[x] " or "[X] " (completed task)
#   - "> " (migrated forward)
#   - "< " (migrated scheduled/back)
_TASK_LINE_RE = re.compile(
    r"^(?P<star>\*\s+)?"
    r"(?:"
    r"(?P<incomplete>•|-\s*\[\s*\]|\[\s*\])"
    r"|(?P<completed>X|-\s*\[[xX]\]|\[[xX]\])"
    r"|(?P<migrated_fwd>>)"
    r"|(?P<migrated_sched><)"
    r")\s+(?P<title>.+?)\s*$"
)


def normalize_task_title(title: str) -> str:
    """Normalize a task title for idempotent matching across OCR runs and page migrations."""
    cleaned = _WHITESPACE_RE.sub(" ", title.strip())
    cleaned = _TRAILING_PUNCT_RE.sub("", cleaned).strip()
    return cleaned.lower()


def _parse_task_line(line: str) -> tuple[str, ExtractedTaskState, bool] | None:
    """Attempt to parse a single unindented line as a rapid-logging task.

    Returns:
        Tuple of (raw_title, state, is_starred) if the line is a task, or None.
    """
    stripped = line.strip()
    if not stripped:
        return None

    # 1. Check signifier followed by strikethrough: "• ~~Call Bob~~" or "* • ~~Call Bob~~"
    sig_strike = _SIGNIFIER_STRIKETHROUGH_RE.match(stripped)
    if sig_strike:
        is_starred = bool(sig_strike.group("star"))
        raw_title = sig_strike.group("title").strip()
        if raw_title and normalize_task_title(raw_title):
            return raw_title, ExtractedTaskState.CANCELLED, is_starred
        return None

    # 2. Check full-line strikethrough: "~~• Call Bob~~", "~~* • Call Bob~~", or "~~Call Bob~~"
    full_strike = _FULL_STRIKETHROUGH_RE.match(stripped)
    if full_strike:
        is_starred = bool(full_strike.group("star"))
        inner = full_strike.group("inner").strip()
        inner_match = _INNER_SIGNIFIER_RE.match(inner)
        if inner_match:
            if inner.startswith("*"):
                is_starred = True
            raw_title = inner_match.group("title").strip()
        else:
            # Skip struck-out notes ("~~- Note~~") or events ("~~o Event~~")
            if re.match(r"^[-o]\s+", inner):
                return None
            raw_title = inner

        if raw_title and normalize_task_title(raw_title):
            return raw_title, ExtractedTaskState.CANCELLED, is_starred
        return None

    # 3. Check standard rapid-logging / checkbox task line
    task_match = _TASK_LINE_RE.match(stripped)
    if not task_match:
        return None

    is_starred = bool(task_match.group("star"))
    raw_title = task_match.group("title").strip()

    # If the title itself is wrapped in ~~...~~, treat as CANCELLED
    if raw_title.startswith("~~") and raw_title.endswith("~~") and len(raw_title) > 4:
        raw_title = raw_title[2:-2].strip()
        state = ExtractedTaskState.CANCELLED
    elif task_match.group("incomplete"):
        state = ExtractedTaskState.INCOMPLETE
    elif task_match.group("completed"):
        state = ExtractedTaskState.COMPLETED
    elif task_match.group("migrated_fwd"):
        state = ExtractedTaskState.MIGRATED_FORWARD
    else:
        state = ExtractedTaskState.MIGRATED_SCHEDULED

    if not raw_title or not normalize_task_title(raw_title):
        return None

    return raw_title, state, is_starred


def parse_page_tasks(text_content: str | None) -> list[ExtractedPageTask]:
    """Parse a page's OCR Markdown transcript into structured rapid-logging tasks.

    Features:
    - Extracts incomplete (`•`, `- [ ]`, `[ ]`), completed (`X`, `- [x]`),
      migrated (`>`, `<`), starred (`* •`), and cancelled (`~~...~~`) tasks.
    - Attaches indented child lines (2+ leading spaces or tab) to the parent task's `detail`.
    - Deduplicates tasks that share the same `normalized_title` on the same page by keeping
      the latest state and merging details.
    """
    if not text_content:
        return []

    tasks: list[ExtractedPageTask] = []
    active_task: ExtractedPageTask | None = None
    active_details: list[str] = []

    def _flush_active_details() -> None:
        nonlocal active_task, active_details
        if active_task is not None and active_details:
            existing = active_task.detail.splitlines() if active_task.detail else []
            combined = existing + active_details
            active_task.detail = "\n".join(combined)
        active_details = []

    for line_idx, raw_line in enumerate(text_content.splitlines(), start=1):
        if not raw_line.strip():
            continue

        # Check if line is indented (2+ spaces or tab)
        leading_spaces = len(raw_line) - len(raw_line.lstrip(" "))
        is_indented = raw_line.startswith("\t") or leading_spaces >= 2

        if is_indented:
            if active_task is not None:
                # Preserve relative indentation beyond the first 2 spaces / 1 tab
                if raw_line.startswith("\t"):
                    cleaned_detail = raw_line[1:].rstrip()
                else:
                    cleaned_detail = raw_line[2:].rstrip()
                if cleaned_detail.strip():
                    active_details.append(cleaned_detail)
            continue

        # Unindented line: flush any accumulated details for the previous task
        _flush_active_details()

        # Check if this line is a task
        parsed = _parse_task_line(raw_line)
        if parsed is not None:
            raw_title, state, is_starred = parsed
            norm_title = normalize_task_title(raw_title)
            task = ExtractedPageTask(
                raw_title=raw_title,
                normalized_title=norm_title,
                state=state,
                is_starred=is_starred,
                detail=None,
                line_number=line_idx,
            )
            tasks.append(task)
            active_task = task
        else:
            # Top-level non-task line (e.g. "- Note", "o Event", heading, paragraph)
            active_task = None

    _flush_active_details()

    # Deduplicate tasks with identical normalized_title on the same page
    deduped_by_key: dict[str, ExtractedPageTask] = {}
    for task in tasks:
        existing = deduped_by_key.get(task.normalized_title)
        if existing is None:
            deduped_by_key[task.normalized_title] = task
        else:
            existing.raw_title = task.raw_title
            existing.state = task.state
            existing.is_starred = existing.is_starred or task.is_starred
            if task.detail:
                existing.detail = (
                    f"{existing.detail}\n{task.detail}"
                    if existing.detail
                    else task.detail
                )
            existing.line_number = task.line_number

    return list(deduped_by_key.values())
