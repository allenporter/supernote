"""In-page exact/fuzzy candidate matching and cross-page/cross-notebook migration selection."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from supernote.server.rapid_log.formatting import normalize_rapid_log_text
from supernote.server.rapid_log.models import (
    EntryLinkState,
    RemoteTaskSnapshot,
    SyncedRapidLogEntry,
    TaskStatus,
)
from supernote.server.utils.rapid_log import (
    RapidLogItem,
    RapidLogKind,
    RapidLogTaskState,
)

__all__ = [
    "EXPLICIT_MIGRATION_STATES",
    "OPEN_TASK_STATES",
    "ParsedCandidate",
    "ResolvedPage",
    "find_migration_source",
    "has_newer_same_notebook_open_owner",
    "in_page_fuzzy_similarity",
    "match_page_candidates",
    "page_chrono_key",
]

# Matches standalone numbers and quarter/version/item numbers (e.g. "1", "q2", "v3", "#4"),
# while ignoring OCR letter-digit confusions embedded inside words (e.g. "b0b").
_DISCRIMINATING_NUM_RE = re.compile(r"(?:^|(?<=[\s#qQvV-]))\d+(?=\b|$)")

OPEN_TASK_STATES = frozenset(
    {
        RapidLogTaskState.INCOMPLETE,
        RapidLogTaskState.MIGRATED_FORWARD,
        RapidLogTaskState.MIGRATED_SCHEDULED,
    }
)
EXPLICIT_MIGRATION_STATES = frozenset(
    {
        RapidLogTaskState.MIGRATED_FORWARD,
        RapidLogTaskState.MIGRATED_SCHEDULED,
    }
)


@dataclass(slots=True)
class ResolvedPage:
    """Resolved page metadata and parsed `RapidLogItem`s ready for matching."""

    file_id: int
    file_path: str
    page_id: str
    page_index: int
    page_modified_ms: int
    page_date_ms: int | None
    page_created_ms: int | None
    chrono_rank: int
    items: tuple[RapidLogItem, ...]


@dataclass(slots=True)
class ParsedCandidate:
    """A parsed `RapidLogItem` anchored to its page order and occurrence index."""

    page: ResolvedPage
    raw_order: int
    item: RapidLogItem
    normalized_text: str
    occurrence_index: int = 0


def page_chrono_key(
    page_created_ms: int | None,
    page_index: int,
    page_id: str,
) -> tuple[int, int, int, str]:
    """Build deterministic chronological sort key for pages within a notebook."""
    return (
        0 if page_created_ms is None else 1,
        page_created_ms or 0,
        page_index,
        page_id,
    )


def in_page_fuzzy_similarity(prev_norm: str, curr_norm: str) -> float:
    """Score similarity for unmatched `TASK` items on the SAME `page_id`, or 0.0 if distinct.

    Supports word-boundary prefix extension/trimming (min 6 chars) and high character
    similarity (>= 0.82, min 8 chars) when discriminating numbers match, preventing
    false matches between numbered items (`Task 1` vs `Task 2`).
    """
    if not prev_norm or not curr_norm:
        return 0.0
    if prev_norm == curr_norm:
        return 1.0

    shorter, longer = (
        (prev_norm, curr_norm)
        if len(prev_norm) <= len(curr_norm)
        else (curr_norm, prev_norm)
    )

    # Word-boundary prefix extension (e.g. appending details onto an existing bullet line)
    if len(shorter) >= 6 and longer.startswith(shorter + " "):
        shorter_nums = _DISCRIMINATING_NUM_RE.findall(shorter)
        longer_nums = _DISCRIMINATING_NUM_RE.findall(longer)
        if longer_nums[: len(shorter_nums)] == shorter_nums:
            return 0.85 + 0.14 * (len(shorter) / len(longer))

    # OCR jitter / minor wording fix: require identical discriminating numbers
    if _DISCRIMINATING_NUM_RE.findall(prev_norm) != _DISCRIMINATING_NUM_RE.findall(
        curr_norm
    ):
        return 0.0
    if len(shorter) < 8:
        return 0.0

    ratio = SequenceMatcher(None, prev_norm, curr_norm).ratio()
    return ratio if ratio >= 0.82 else 0.0


def _pair_exact_bucket(
    curr_indices: Sequence[int],
    prev_indices: Sequence[int],
    raw_candidates: Sequence[ParsedCandidate],
    prev_list: Sequence[SyncedRapidLogEntry],
    curr_matched_prev: dict[int, int],
    used_prev_indices: set[int],
) -> None:
    """Pair items sharing identical `(kind, normalized_text)` on the same page.

    When occurrence counts are unchanged, pairs positionally so visual slots are stable.
    When an identical duplicate was inserted or erased, pairs unchanged `(task_state,
    is_starred, detail)` entries first so erasing a top completed duplicate does not
    shift its state onto a remaining open duplicate below.
    """
    if len(curr_indices) == len(prev_indices):
        for c_idx, p_idx in zip(curr_indices, prev_indices, strict=True):
            curr_matched_prev[c_idx] = p_idx
            used_prev_indices.add(p_idx)
        return

    for c_idx in curr_indices:
        cand_item = raw_candidates[c_idx].item
        cand_sig = (
            cand_item.task_state,
            cand_item.is_starred,
            (cand_item.detail or "").strip(),
        )
        for p_idx in prev_indices:
            if p_idx in used_prev_indices:
                continue
            p_entry = prev_list[p_idx]
            prev_sig = (
                p_entry.task_state,
                p_entry.is_starred,
                (p_entry.detail or "").strip(),
            )
            if cand_sig == prev_sig:
                curr_matched_prev[c_idx] = p_idx
                used_prev_indices.add(p_idx)
                break

    rem_curr = [c_idx for c_idx in curr_indices if c_idx not in curr_matched_prev]
    rem_prev = [p_idx for p_idx in prev_indices if p_idx not in used_prev_indices]
    for c_idx, p_idx in zip(rem_curr, rem_prev, strict=False):
        curr_matched_prev[c_idx] = p_idx
        used_prev_indices.add(p_idx)


def match_page_candidates(
    rp: ResolvedPage,
    prev_list: Sequence[SyncedRapidLogEntry],
) -> tuple[
    list[tuple[ParsedCandidate, SyncedRapidLogEntry]],
    list[ParsedCandidate],
    list[SyncedRapidLogEntry],
]:
    """Match current items on `rp` against `prev_list` via exact and fuzzy passes."""
    raw_candidates = [
        ParsedCandidate(
            page=rp,
            raw_order=idx,
            item=item,
            normalized_text=normalize_rapid_log_text(item.text),
        )
        for idx, item in enumerate(rp.items)
    ]

    prev_exact_buckets: dict[tuple[RapidLogKind, str], list[int]] = defaultdict(list)
    for p_idx, p_entry in enumerate(prev_list):
        prev_exact_buckets[(p_entry.kind, p_entry.normalized_text)].append(p_idx)

    curr_exact_buckets: dict[tuple[RapidLogKind, str], list[int]] = defaultdict(list)
    for c_idx, cand in enumerate(raw_candidates):
        curr_exact_buckets[(cand.item.kind, cand.normalized_text)].append(c_idx)

    used_prev_indices: set[int] = set()
    curr_matched_prev: dict[int, int] = {}

    for key, curr_indices in curr_exact_buckets.items():
        prev_indices = prev_exact_buckets.get(key)
        if prev_indices:
            _pair_exact_bucket(
                curr_indices,
                prev_indices,
                raw_candidates,
                prev_list,
                curr_matched_prev,
                used_prev_indices,
            )

    fuzzy_scores: list[tuple[float, int, int]] = []
    for c_idx, cand in enumerate(raw_candidates):
        if c_idx in curr_matched_prev or cand.item.kind != RapidLogKind.TASK:
            continue
        for p_idx, p_entry in enumerate(prev_list):
            if p_idx in used_prev_indices or p_entry.kind != RapidLogKind.TASK:
                continue
            score = in_page_fuzzy_similarity(
                p_entry.normalized_text, cand.normalized_text
            )
            if score > 0.0:
                fuzzy_scores.append((score, c_idx, p_idx))

    for _, c_idx, p_idx in sorted(fuzzy_scores, key=lambda t: (-t[0], t[1], t[2])):
        if c_idx not in curr_matched_prev and p_idx not in used_prev_indices:
            curr_matched_prev[c_idx] = p_idx
            used_prev_indices.add(p_idx)

    # Drop unmatched bulletless strikethroughs (crossed-out prose that was never a task)
    kept_candidates: list[tuple[int, ParsedCandidate]] = []
    occ_counts: dict[tuple[RapidLogKind, str], int] = defaultdict(int)
    for c_idx, cand in enumerate(raw_candidates):
        if (
            c_idx not in curr_matched_prev
            and cand.item.kind == RapidLogKind.TASK
            and not cand.item.has_explicit_bullet
            and cand.item.is_cancelled
        ):
            continue
        occ_key = (cand.item.kind, cand.normalized_text)
        cand.occurrence_index = occ_counts[occ_key]
        occ_counts[occ_key] += 1
        kept_candidates.append((c_idx, cand))

    matched: list[tuple[ParsedCandidate, SyncedRapidLogEntry]] = []
    unmatched_new: list[ParsedCandidate] = []
    for final_order, (c_idx, cand) in enumerate(kept_candidates):
        cand.raw_order = final_order
        if c_idx in curr_matched_prev:
            matched.append((cand, prev_list[curr_matched_prev[c_idx]]))
        else:
            unmatched_new.append(cand)

    unmatched_prev = [
        p_entry
        for p_idx, p_entry in enumerate(prev_list)
        if p_idx not in used_prev_indices
    ]
    return matched, unmatched_new, unmatched_prev


def find_migration_source(
    cand: ParsedCandidate,
    *,
    working_entries: Sequence[SyncedRapidLogEntry],
    unmatched_prev_entries: Sequence[SyncedRapidLogEntry],
    handed_off_prev_ids: set[int],
    working_external: Sequence[SyncedRapidLogEntry],
    effective_tasks: Mapping[str, RemoteTaskSnapshot],
    cancelled_target: bool = False,
) -> tuple[str, int, SyncedRapidLogEntry] | None:
    """Find the highest-priority open ACTIVE entry eligible to hand off its `ScheduleTask`."""
    file_id = cand.page.file_id
    target_norm = cand.normalized_text
    target_is_completed = cand.item.task_state == RapidLogTaskState.COMPLETED
    cand_chrono = page_chrono_key(
        cand.page.page_created_ms, cand.page.page_index, cand.page.page_id
    )
    best_choice: (
        tuple[tuple[int, int, int, int], str, int, SyncedRapidLogEntry] | None
    ) = None

    def _consider(
        pool_name: str,
        idx: int,
        src: SyncedRapidLogEntry,
        *,
        require_explicit_migration: bool,
    ) -> None:
        nonlocal best_choice
        if (
            src.kind != RapidLogKind.TASK
            or src.normalized_text != target_norm
            or src.link_state != EntryLinkState.ACTIVE
            or src.schedule_task_id is None
        ):
            return
        if src.file_id == file_id and src.page_id == cand.page.page_id:
            return

        remote = effective_tasks.get(src.schedule_task_id)
        if remote is None or remote.status == TaskStatus.COMPLETED:
            return

        is_explicit_mig = src.task_state in EXPLICIT_MIGRATION_STATES
        if cancelled_target:
            if src.file_id != file_id or not is_explicit_mig:
                return
            src_chrono = page_chrono_key(
                src.page_created_ms, src.page_index, src.page_id
            )
            if src_chrono >= cand_chrono:
                return
        else:
            if require_explicit_migration and not is_explicit_mig:
                return
            if target_is_completed and not is_explicit_mig:
                return
            if not is_explicit_mig and src.task_state != RapidLogTaskState.INCOMPLETE:
                return

        if src.file_id == file_id and is_explicit_mig:
            tier = 0
        elif pool_name == "unmatched_prev":
            tier = 1
        elif src.file_id != file_id and is_explicit_mig:
            tier = 2
        else:
            src_chrono = page_chrono_key(
                src.page_created_ms, src.page_index, src.page_id
            )
            if src_chrono >= cand_chrono:
                return
            tier = 3

        sort_key = (tier, src.page_created_ms or 0, src.page_index, src.item_order)
        if best_choice is None or sort_key < best_choice[0]:
            best_choice = (sort_key, pool_name, idx, src)

    for idx, src in enumerate(working_entries):
        _consider("working", idx, src, require_explicit_migration=False)
    if not cancelled_target:
        for idx, src in enumerate(unmatched_prev_entries):
            if idx not in handed_off_prev_ids:
                _consider("unmatched_prev", idx, src, require_explicit_migration=False)
        for idx, src in enumerate(working_external):
            _consider("external", idx, src, require_explicit_migration=True)

    if best_choice is None:
        return None
    _, pool_name, idx, src = best_choice
    return pool_name, idx, src


def has_newer_same_notebook_open_owner(
    cand: ParsedCandidate,
    working_entries: Sequence[SyncedRapidLogEntry],
    effective_tasks: Mapping[str, RemoteTaskSnapshot],
) -> bool:
    """Return True if a chronologically newer page in the same notebook already owns an open task for `cand`."""
    cand_chrono = page_chrono_key(
        cand.page.page_created_ms, cand.page.page_index, cand.page.page_id
    )
    for src in working_entries:
        if (
            src.file_id != cand.page.file_id
            or src.page_id == cand.page.page_id
            or src.kind != RapidLogKind.TASK
            or src.normalized_text != cand.normalized_text
            or src.link_state != EntryLinkState.ACTIVE
            or src.schedule_task_id is None
        ):
            continue
        remote = effective_tasks.get(src.schedule_task_id)
        if remote is None or remote.status == TaskStatus.COMPLETED:
            continue
        src_chrono = page_chrono_key(src.page_created_ms, src.page_index, src.page_id)
        if src_chrono > cand_chrono:
            return True
    return False
