"""Parser for Bullet Journal Rapid Logging notation and Markdown checkboxes in OCR transcripts."""

import re
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "RapidLogItem",
    "RapidLogKind",
    "RapidLogTaskState",
    "parse_rapid_log",
]


class RapidLogKind(str, Enum):
    """Bullet Journal Rapid Logging entry kind (per OCR legend)."""

    TASK = "TASK"
    EVENT = "EVENT"
    NOTE = "NOTE"


class RapidLogTaskState(str, Enum):
    """Lifecycle state of a Rapid Logging task bullet or checkbox."""

    INCOMPLETE = "INCOMPLETE"
    COMPLETED = "COMPLETED"
    MIGRATED_FORWARD = "MIGRATED_FORWARD"
    MIGRATED_SCHEDULED = "MIGRATED_SCHEDULED"
    CANCELLED = "CANCELLED"


@dataclass(slots=True)
class RapidLogItem:
    """Structured representation of a Rapid Logging entry and its nested hierarchy."""

    kind: RapidLogKind
    text: str
    task_state: RapidLogTaskState | None = None
    is_starred: bool = False
    is_cancelled: bool = False
    detail: str | None = None
    children: list["RapidLogItem"] = field(default_factory=list)
    line_number: int = 0


# Signifier + bullet followed by strikethrough text:
# e.g. "• ~~Call Bob~~", "* o ~~4pm Sync~~", "- ~~Old note~~"
_BULLET_STRIKETHROUGH_RE = re.compile(
    r"^(?P<star>\*\s+)?"
    r"(?:"
    r"(?P<task>[•X><]|-\s*\[[ xX]\]|\[[ xX]\])"
    r"|(?P<event>o)"
    r"|(?P<note>-)"
    r")\s+~~\s*(?P<text>.+?)\s*~~\s*$"
)

# Full-line strikethrough: "~~...~~" or "* ~~...~~"
_FULL_STRIKETHROUGH_RE = re.compile(r"^(?P<star>\*\s+)?~~\s*(?P<inner>.+?)\s*~~\s*$")

# Inner bullet inside full-line strikethrough:
# e.g. "~~* • Call Bob~~", "~~o 4pm Sync~~", "~~- Old note~~"
_INNER_BULLET_RE = re.compile(
    r"^(?P<star>\*\s+)?"
    r"(?:"
    r"(?P<task>[•X><]|-\s*\[[ xX]\]|\[[ xX]\])"
    r"|(?P<event>o)"
    r"|(?P<note>-)"
    r")\s+(?P<text>.+?)\s*$"
)

# Active task line patterns (checked before `-` note pattern so `- [ ]` matches as TASK):
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
    r")\s+(?P<text>.+?)\s*$"
)

# Event ("o ...") and Note ("- ...") lines, with optional "* " critical signifier
_EVENT_OR_NOTE_LINE_RE = re.compile(
    r"^(?P<star>\*\s+)?(?:(?P<event>o)|(?P<note>-))\s+(?P<text>.+?)\s*$"
)


def _unwrap_tilde_text(raw_text: str) -> tuple[str, bool]:
    """Strip surrounding `~~...~~` if present and return `(cleaned_text, was_struck)`."""
    if raw_text.startswith("~~") and raw_text.endswith("~~") and len(raw_text) > 4:
        return raw_text[2:-2].strip(), True
    return raw_text, False


def _parse_rapid_log_line(stripped: str, line_number: int) -> RapidLogItem | None:
    """Parse a single stripped line into a `RapidLogItem`, or `None` if not a Rapid Log entry."""
    if not stripped:
        return None

    # 1. Bullet followed by strikethrough text: "• ~~Call Bob~~", "o ~~Sync~~", "- ~~Note~~"
    bullet_strike = _BULLET_STRIKETHROUGH_RE.match(stripped)
    if bullet_strike:
        text = bullet_strike.group("text").strip()
        if not text:
            return None
        is_starred = bool(bullet_strike.group("star"))
        if bullet_strike.group("event"):
            return RapidLogItem(
                kind=RapidLogKind.EVENT,
                text=text,
                is_starred=is_starred,
                is_cancelled=True,
                line_number=line_number,
            )
        if bullet_strike.group("note"):
            return RapidLogItem(
                kind=RapidLogKind.NOTE,
                text=text,
                is_starred=is_starred,
                is_cancelled=True,
                line_number=line_number,
            )
        return RapidLogItem(
            kind=RapidLogKind.TASK,
            text=text,
            task_state=RapidLogTaskState.CANCELLED,
            is_starred=is_starred,
            is_cancelled=True,
            line_number=line_number,
        )

    # 2. Full-line strikethrough: "~~• Call Bob~~", "~~o 4pm Sync~~", "~~- Old note~~", or "~~Call Bob~~"
    full_strike = _FULL_STRIKETHROUGH_RE.match(stripped)
    if full_strike:
        is_starred = bool(full_strike.group("star"))
        inner = full_strike.group("inner").strip()
        inner_match = _INNER_BULLET_RE.match(inner)
        if inner_match:
            is_starred = is_starred or bool(inner_match.group("star"))
            text = inner_match.group("text").strip()
            if not text:
                return None
            if inner_match.group("event"):
                return RapidLogItem(
                    kind=RapidLogKind.EVENT,
                    text=text,
                    is_starred=is_starred,
                    is_cancelled=True,
                    line_number=line_number,
                )
            if inner_match.group("note"):
                return RapidLogItem(
                    kind=RapidLogKind.NOTE,
                    text=text,
                    is_starred=is_starred,
                    is_cancelled=True,
                    line_number=line_number,
                )
            return RapidLogItem(
                kind=RapidLogKind.TASK,
                text=text,
                task_state=RapidLogTaskState.CANCELLED,
                is_starred=is_starred,
                is_cancelled=True,
                line_number=line_number,
            )
        if not inner:
            return None
        # Bare strikethrough without visible bullet (e.g. heavy ink scribble over a task)
        return RapidLogItem(
            kind=RapidLogKind.TASK,
            text=inner,
            task_state=RapidLogTaskState.CANCELLED,
            is_starred=is_starred,
            is_cancelled=True,
            line_number=line_number,
        )

    # 3. Standard Rapid Logging task or Markdown checkbox (checked before `-` note)
    task_match = _TASK_LINE_RE.match(stripped)
    if task_match:
        is_starred = bool(task_match.group("star"))
        text, was_struck = _unwrap_tilde_text(task_match.group("text").strip())
        if not text:
            return None
        if was_struck:
            state = RapidLogTaskState.CANCELLED
        elif task_match.group("incomplete"):
            state = RapidLogTaskState.INCOMPLETE
        elif task_match.group("completed"):
            state = RapidLogTaskState.COMPLETED
        elif task_match.group("migrated_fwd"):
            state = RapidLogTaskState.MIGRATED_FORWARD
        else:
            state = RapidLogTaskState.MIGRATED_SCHEDULED
        return RapidLogItem(
            kind=RapidLogKind.TASK,
            text=text,
            task_state=state,
            is_starred=is_starred,
            is_cancelled=(state == RapidLogTaskState.CANCELLED),
            line_number=line_number,
        )

    # 4. Event ("o ...") or Note ("- ...")
    ev_note_match = _EVENT_OR_NOTE_LINE_RE.match(stripped)
    if ev_note_match:
        is_starred = bool(ev_note_match.group("star"))
        text, was_struck = _unwrap_tilde_text(ev_note_match.group("text").strip())
        if not text:
            return None
        kind = RapidLogKind.EVENT if ev_note_match.group("event") else RapidLogKind.NOTE
        return RapidLogItem(
            kind=kind,
            text=text,
            is_starred=is_starred,
            is_cancelled=was_struck,
            line_number=line_number,
        )

    return None


def parse_rapid_log(text_content: str | None) -> list[RapidLogItem]:
    """Parse an OCR Markdown page transcript into structured Rapid Logging entries.

    Supports:
    - Tasks (`•`, `X`, `>`, `<`, `[ ]`, `[x]`, `- [ ]`, `- [x]`)
    - Events (`o`)
    - Notes (`-`)
    - Critical signifiers (`* `) and strikethrough cancellations (`~~...~~`)
    - Nested indentation (2+ spaces or tabs per level), populating both recursive
      `children` and dedented `detail` text on parent items.
    """
    if not text_content:
        return []

    items: list[RapidLogItem] = []
    # Stack of (indent_spaces, item) for tracking nested children
    stack: list[tuple[int, RapidLogItem]] = []

    for line_idx, raw_line in enumerate(text_content.splitlines(), start=1):
        if not raw_line.strip():
            continue

        expanded = raw_line.expandtabs(2)
        stripped = expanded.lstrip(" ").rstrip()
        indent = len(expanded.rstrip()) - len(stripped)

        if indent >= 2:
            if not stack:
                # Indented text not nested under any Rapid Log item (e.g. under a plain heading)
                continue

            while len(stack) > 1 and stack[-1][0] >= indent:
                stack.pop()

            for anc_indent, anc_item in stack:
                slice_pos = min(indent, anc_indent + 2)
                rel_line = expanded[slice_pos:].rstrip()
                if rel_line.strip():
                    anc_item.detail = (
                        f"{anc_item.detail}\n{rel_line}"
                        if anc_item.detail
                        else rel_line
                    )

            child = _parse_rapid_log_line(stripped, line_idx)
            if child is None:
                child = RapidLogItem(
                    kind=RapidLogKind.NOTE,
                    text=stripped,
                    line_number=line_idx,
                )
            stack[-1][1].children.append(child)
            stack.append((indent, child))
            continue

        # Top-level line (indent < 2)
        parsed = _parse_rapid_log_line(stripped, line_idx)
        if parsed is not None:
            items.append(parsed)
            stack = [(indent, parsed)]
        else:
            stack.clear()

    return items
