"""Top-level Rapid Logging lifecycle state machine and notebook reconciliation planner."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from supernote.server.rapid_log.actions import ActionAccumulator
from supernote.server.rapid_log.formatting import (
    build_note_task_link,
    expected_importance,
    expected_status,
    format_migrated_detail,
    format_task_title_and_detail,
    infer_page_created_ms,
    infer_page_date_ms,
    merge_migrated_detail,
    normalize_due_time,
    strip_overlong_headline_prefix,
)
from supernote.server.rapid_log.matching import (
    OPEN_TASK_STATES,
    ParsedCandidate,
    ResolvedPage,
    find_migration_source,
    has_newer_same_notebook_open_owner,
    match_page_candidates,
    page_chrono_key,
)
from supernote.server.rapid_log.models import (
    DeleteTaskAction,
    EntryLinkState,
    NotebookPageInput,
    ReconciliationPlan,
    RemoteTaskSnapshot,
    SyncedRapidLogEntry,
    TaskImportance,
    TaskStatus,
)
from supernote.server.utils.rapid_log import (
    RapidLogItem,
    RapidLogKind,
    RapidLogTaskState,
    parse_rapid_log,
)
from supernote.server.utils.unique_id import next_id

__all__ = [
    "plan_notebook_deletion",
    "reconcile_rapid_log",
]


def _default_task_id_factory() -> str:
    return str(next_id())


def _build_synced_entry(
    cand: ParsedCandidate,
    *,
    link_state: EntryLinkState,
    schedule_task_id: str | None,
    last_synced_ms: int,
    entry_id: int | str | None = None,
) -> SyncedRapidLogEntry:
    rp = cand.page
    item = cand.item
    return SyncedRapidLogEntry(
        file_id=rp.file_id,
        file_path=rp.file_path,
        page_id=rp.page_id,
        page_index=rp.page_index,
        item_order=cand.raw_order,
        occurrence_index=cand.occurrence_index,
        kind=item.kind,
        normalized_text=cand.normalized_text,
        text=item.text,
        detail=item.detail,
        task_state=item.task_state if item.kind == RapidLogKind.TASK else None,
        is_starred=item.is_starred,
        is_cancelled=item.is_cancelled,
        page_date_ms=rp.page_date_ms,
        page_created_ms=rp.page_created_ms,
        link_state=link_state,
        schedule_task_id=schedule_task_id,
        last_synced_ms=last_synced_ms,
        entry_id=entry_id,
    )


def _resolve_matched_detail_update(
    prev_entry: SyncedRapidLogEntry,
    item: RapidLogItem,
    curr_detail: str,
    prev_detail: str,
    remote_detail: str | None,
    *,
    ink_wins_tie: bool,
) -> str | None:
    """Compute next `detail` when ink detail/headline changed, preserving migrated prefixes."""
    if curr_detail == prev_detail:
        return None

    prev_sub = strip_overlong_headline_prefix(prev_entry.detail, prev_entry.text)
    curr_sub = strip_overlong_headline_prefix(item.detail, item.text)
    remote_sub = strip_overlong_headline_prefix(remote_detail, prev_entry.text)

    if remote_sub == prev_sub:
        return curr_detail
    if prev_sub and remote_sub.endswith("\n" + prev_sub):
        prefix = remote_sub[: -(len(prev_sub) + 1)]
        next_sub = f"{prefix}\n{curr_sub}" if curr_sub else prefix
        return format_task_title_and_detail(item.text, next_sub)[1]
    if not prev_sub and curr_sub and remote_sub:
        merged_sub = merge_migrated_detail(remote_sub, curr_sub)
        return format_task_title_and_detail(item.text, merged_sub)[1]
    if ink_wins_tie:
        return curr_detail
    return None


def _reconcile_active_matched_entry(
    cand: ParsedCandidate,
    prev_entry: SyncedRapidLogEntry,
    task_id: str,
    acc: ActionAccumulator,
    sync_time_ms: int,
    new_synced_ms: int,
) -> tuple[EntryLinkState, str | None, int]:
    """Reconcile an `ACTIVE` matched entry via per-field 3-way diff and timestamp tie-breaking."""
    remote = acc.effective_tasks.get(task_id)
    if remote is None:
        return EntryLinkState.DISMISSED_DIGITAL, None, new_synced_ms

    item = cand.item
    if item.is_cancelled or item.task_state == RapidLogTaskState.CANCELLED:
        if remote.status != TaskStatus.COMPLETED:
            acc.record_delete(task_id, reason="cancelled_ink")
        return EntryLinkState.CANCELLED_INK, None, new_synced_ms

    rp = cand.page
    ink_mod_ms = rp.page_modified_ms
    write_mod_ms = rp.page_modified_ms or sync_time_ms
    ink_wins_tie = ink_mod_ms >= remote.update_time

    curr_title, curr_detail = format_task_title_and_detail(item.text, item.detail)
    prev_title, prev_detail = format_task_title_and_detail(
        prev_entry.text, prev_entry.detail
    )

    updates: dict[str, Any] = {}
    reasons: list[str] = []

    prev_comp = prev_entry.task_state == RapidLogTaskState.COMPLETED
    curr_comp = item.task_state == RapidLogTaskState.COMPLETED
    if prev_comp != curr_comp:
        desired_status = TaskStatus.COMPLETED if curr_comp else TaskStatus.NEEDS_ACTION
        digital_status_changed = remote.status != expected_status(prev_entry.task_state)
        if remote.status != desired_status and (
            not digital_status_changed or ink_wins_tie
        ):
            updates["status"] = desired_status
            updates["completed_time"] = (
                max(write_mod_ms, sync_time_ms) if curr_comp else 0
            )
            reasons.append("ink_completed" if curr_comp else "ink_reopened")

    if prev_entry.is_starred != item.is_starred:
        digital_imp_changed = (
            remote.importance or TaskImportance.NORMAL
        ) != expected_importance(prev_entry.is_starred)
        if not digital_imp_changed or ink_wins_tie:
            updates["importance"] = expected_importance(item.is_starred)
            reasons.append("ink_importance")

    if curr_title != prev_title and (remote.title == prev_title or ink_wins_tie):
        updates["title"] = curr_title
        reasons.append("ink_title")

    next_detail = _resolve_matched_detail_update(
        prev_entry,
        item,
        curr_detail,
        prev_detail,
        remote.detail,
        ink_wins_tie=ink_wins_tie,
    )
    if next_detail is not None:
        updates["detail"] = next_detail
        reasons.append("ink_detail")

    anchor_changed = (
        rp.file_id != prev_entry.file_id
        or rp.file_path != prev_entry.file_path
        or rp.page_index != prev_entry.page_index
        or rp.page_id != prev_entry.page_id
    )
    if anchor_changed or "title" in updates or not remote.links:
        desired_links = build_note_task_link(
            file_id=rp.file_id,
            file_path=rp.file_path,
            page_index=rp.page_index,
            page_id=rp.page_id,
            task_title=updates.get("title", remote.title),
        )
        if remote.links != desired_links:
            updates["links"] = desired_links
            reasons.append("anchor_updated")

    if updates:
        acc.record_update(
            task_id,
            updates,
            reason="+".join(reasons),
            modified_ms=write_mod_ms,
        )
    updated_remote = acc.effective_tasks.get(task_id)
    if updated_remote is not None:
        new_synced_ms = max(new_synced_ms, updated_remote.update_time)
    return EntryLinkState.ACTIVE, task_id, new_synced_ms


def _reconcile_matched_entry(
    cand: ParsedCandidate,
    prev_entry: SyncedRapidLogEntry,
    acc: ActionAccumulator,
    sync_time_ms: int,
) -> SyncedRapidLogEntry:
    """Reconcile a matched item against `prev_entry` and `acc.effective_tasks`."""
    rp = cand.page
    item = cand.item
    write_mod_ms = rp.page_modified_ms or sync_time_ms
    new_synced_ms = max(sync_time_ms, write_mod_ms, prev_entry.last_synced_ms)

    if item.kind != RapidLogKind.TASK:
        return _build_synced_entry(
            cand,
            link_state=EntryLinkState.UNLINKED,
            schedule_task_id=None,
            last_synced_ms=new_synced_ms,
            entry_id=prev_entry.entry_id,
        )

    link_state = prev_entry.link_state
    task_id = prev_entry.schedule_task_id

    if link_state == EntryLinkState.ACTIVE and task_id is not None:
        link_state, task_id, new_synced_ms = _reconcile_active_matched_entry(
            cand, prev_entry, task_id, acc, sync_time_ms, new_synced_ms
        )
        return _build_synced_entry(
            cand,
            link_state=link_state,
            schedule_task_id=task_id,
            last_synced_ms=new_synced_ms,
            entry_id=prev_entry.entry_id,
        )

    curr_title, curr_detail = format_task_title_and_detail(item.text, item.detail)
    curr_links = build_note_task_link(
        file_id=rp.file_id,
        file_path=rp.file_path,
        page_index=rp.page_index,
        page_id=rp.page_id,
        task_title=curr_title,
    )

    should_create = False
    if link_state in (EntryLinkState.UNLINKED, EntryLinkState.CANCELLED_INK):
        should_create = not item.is_cancelled and item.task_state in OPEN_TASK_STATES
    elif link_state == EntryLinkState.DISMISSED_DIGITAL:
        should_create = (
            prev_entry.task_state
            in (RapidLogTaskState.COMPLETED, RapidLogTaskState.CANCELLED)
            and item.task_state == RapidLogTaskState.INCOMPLETE
            and not item.is_cancelled
        )

    if should_create:
        task_id = acc.record_create(
            title=curr_title,
            detail=curr_detail,
            importance=expected_importance(item.is_starred),
            due_time=rp.page_date_ms,
            links=curr_links,
            modified_ms=write_mod_ms,
        )
        link_state = EntryLinkState.ACTIVE
        new_synced_ms = max(new_synced_ms, acc.effective_tasks[task_id].update_time)

    return _build_synced_entry(
        cand,
        link_state=link_state,
        schedule_task_id=task_id,
        last_synced_ms=new_synced_ms,
        entry_id=prev_entry.entry_id,
    )


def _resolve_pages(
    file_id: int,
    file_path: str,
    pages: Sequence[NotebookPageInput],
) -> list[ResolvedPage]:
    """Resolve page timestamps, parse Rapid Logging items, and sort chronologically."""
    raw_pages = [
        ResolvedPage(
            file_id=file_id,
            file_path=file_path,
            page_id=p.page_id,
            page_index=p.page_index,
            page_modified_ms=p.page_modified_ms,
            page_date_ms=(
                p.page_date_ms
                if p.page_date_ms is not None
                else infer_page_date_ms(p.page_id)
            ),
            page_created_ms=(
                p.page_created_ms
                if p.page_created_ms is not None
                else infer_page_created_ms(p.page_id)
            ),
            chrono_rank=0,
            items=(
                p.items
                if p.items is not None
                else tuple(parse_rapid_log(p.text_content))
            ),
        )
        for p in pages
    ]
    chrono_pages = sorted(
        raw_pages,
        key=lambda rp: page_chrono_key(rp.page_created_ms, rp.page_index, rp.page_id),
    )
    for rank, rp in enumerate(chrono_pages):
        rp.chrono_rank = rank
    return chrono_pages


def _normalize_baselines(
    prev_entries: Sequence[SyncedRapidLogEntry],
    external_entries: Sequence[SyncedRapidLogEntry],
    remote_tasks: Mapping[str, RemoteTaskSnapshot],
    file_id: int,
) -> tuple[
    dict[str, list[SyncedRapidLogEntry]],
    list[SyncedRapidLogEntry],
    set[int],
]:
    """Normalize input baselines, tombstoning deleted tasks and healing duplicate ACTIVE owners."""

    def _tombstone_missing(entry: SyncedRapidLogEntry) -> SyncedRapidLogEntry:
        if entry.link_state != EntryLinkState.ACTIVE:
            return entry
        if entry.schedule_task_id is None or entry.schedule_task_id not in remote_tasks:
            return replace(
                entry,
                link_state=EntryLinkState.DISMISSED_DIGITAL,
                schedule_task_id=None,
            )
        return entry

    local_entries = [
        _tombstone_missing(e) for e in prev_entries if e.file_id == file_id
    ]
    ext_entries = [
        _tombstone_missing(e) for e in external_entries if e.file_id != file_id
    ]
    external_dirty_indices: set[int] = set()

    # Self-heal crash-recovered state if multiple ACTIVE rows reference the same task_id
    owners_by_task: dict[str, list[tuple[str, int, SyncedRapidLogEntry]]] = defaultdict(
        list
    )
    for idx, entry in enumerate(local_entries):
        if entry.link_state == EntryLinkState.ACTIVE and entry.schedule_task_id:
            owners_by_task[entry.schedule_task_id].append(("local", idx, entry))
    for idx, entry in enumerate(ext_entries):
        if entry.link_state == EntryLinkState.ACTIVE and entry.schedule_task_id:
            owners_by_task[entry.schedule_task_id].append(("ext", idx, entry))

    for group in owners_by_task.values():
        if len(group) <= 1:
            continue
        winner = max(
            group,
            key=lambda item: (
                0 if item[2].page_created_ms is None else 1,
                item[2].page_created_ms or 0,
                item[2].last_synced_ms,
                item[2].page_index,
                item[2].item_order,
            ),
        )
        for pool, idx, entry in group:
            if (pool, idx) == (winner[0], winner[1]):
                continue
            demoted = replace(
                entry, link_state=EntryLinkState.MIGRATED, schedule_task_id=None
            )
            if pool == "local":
                local_entries[idx] = demoted
            else:
                ext_entries[idx] = demoted
                external_dirty_indices.add(idx)

    prev_by_page: dict[str, list[SyncedRapidLogEntry]] = defaultdict(list)
    for entry in local_entries:
        prev_by_page[entry.page_id].append(entry)
    for page_list in prev_by_page.values():
        page_list.sort(key=lambda e: (e.item_order, e.occurrence_index))

    return prev_by_page, ext_entries, external_dirty_indices


def _retire_migration_source(
    pool_name: str,
    pool_idx: int,
    src_entry: SyncedRapidLogEntry,
    *,
    sync_time_ms: int,
    working_entries: list[SyncedRapidLogEntry],
    handed_off_prev_ids: set[int],
    working_external: list[SyncedRapidLogEntry],
    external_dirty_indices: set[int],
) -> None:
    """Transition a handed-off source entry to `EntryLinkState.MIGRATED`."""
    retired_src = replace(
        src_entry,
        link_state=EntryLinkState.MIGRATED,
        schedule_task_id=None,
        last_synced_ms=max(src_entry.last_synced_ms, sync_time_ms),
    )
    if pool_name == "working":
        working_entries[pool_idx] = retired_src
    elif pool_name == "unmatched_prev":
        handed_off_prev_ids.add(pool_idx)
    elif pool_name == "external":
        working_external[pool_idx] = retired_src
        external_dirty_indices.add(pool_idx)


def _apply_migration_handoff(
    cand: ParsedCandidate,
    src_entry: SyncedRapidLogEntry,
    adopted_task_id: str,
    acc: ActionAccumulator,
    *,
    write_mod_ms: int,
    sync_time_ms: int,
) -> int:
    """Advance deep-link, detail, importance, due date, and completion on a handed-off task."""
    rp = cand.page
    item = cand.item
    remote = acc.effective_tasks[adopted_task_id]

    handoff_updates: dict[str, Any] = {
        "links": build_note_task_link(
            file_id=rp.file_id,
            file_path=rp.file_path,
            page_index=rp.page_index,
            page_id=rp.page_id,
            task_title=remote.title,
        )
    }
    merged_detail = format_migrated_detail(remote.detail, item.text, item.detail)
    if merged_detail != (remote.detail or ""):
        handoff_updates["detail"] = merged_detail
    if item.is_starred and remote.importance != TaskImportance.HIGH:
        handoff_updates["importance"] = TaskImportance.HIGH

    curr_remote_due = normalize_due_time(remote.due_time)
    if rp.page_date_ms is not None and (
        curr_remote_due == normalize_due_time(src_entry.page_date_ms)
        or (curr_remote_due is not None and curr_remote_due < rp.page_date_ms)
        or (src_entry.page_date_ms is None and curr_remote_due is None)
    ):
        handoff_updates["due_time"] = rp.page_date_ms

    if item.task_state == RapidLogTaskState.COMPLETED:
        handoff_updates["status"] = TaskStatus.COMPLETED
        handoff_updates["completed_time"] = max(write_mod_ms, sync_time_ms)

    acc.record_update(
        adopted_task_id,
        handoff_updates,
        reason="migrated_handoff",
        modified_ms=write_mod_ms,
    )
    return acc.effective_tasks[adopted_task_id].update_time


def _reconcile_new_candidate(
    cand: ParsedCandidate,
    *,
    working_entries: list[SyncedRapidLogEntry],
    unmatched_prev_entries: Sequence[SyncedRapidLogEntry],
    handed_off_prev_ids: set[int],
    working_external: list[SyncedRapidLogEntry],
    external_dirty_indices: set[int],
    acc: ActionAccumulator,
    sync_time_ms: int,
) -> SyncedRapidLogEntry:
    """Reconcile an unmatched candidate (migration handoff, cancelled migration, or fresh create)."""
    rp = cand.page
    item = cand.item
    write_mod_ms = rp.page_modified_ms or sync_time_ms
    new_synced_ms = max(sync_time_ms, write_mod_ms)

    if item.kind != RapidLogKind.TASK:
        return _build_synced_entry(
            cand,
            link_state=EntryLinkState.UNLINKED,
            schedule_task_id=None,
            last_synced_ms=new_synced_ms,
        )

    if item.is_cancelled or item.task_state == RapidLogTaskState.CANCELLED:
        if item.has_explicit_bullet:
            cancelled_mig = find_migration_source(
                cand,
                working_entries=working_entries,
                unmatched_prev_entries=unmatched_prev_entries,
                handed_off_prev_ids=handed_off_prev_ids,
                working_external=working_external,
                effective_tasks=acc.effective_tasks,
                cancelled_target=True,
            )
            if cancelled_mig is not None:
                pool_name, pool_idx, src_entry = cancelled_mig
                _retire_migration_source(
                    pool_name,
                    pool_idx,
                    src_entry,
                    sync_time_ms=sync_time_ms,
                    working_entries=working_entries,
                    handed_off_prev_ids=handed_off_prev_ids,
                    working_external=working_external,
                    external_dirty_indices=external_dirty_indices,
                )
                if src_entry.schedule_task_id is not None:
                    acc.record_delete(
                        src_entry.schedule_task_id, reason="cancelled_ink"
                    )
                return _build_synced_entry(
                    cand,
                    link_state=EntryLinkState.CANCELLED_INK,
                    schedule_task_id=None,
                    last_synced_ms=new_synced_ms,
                )
        return _build_synced_entry(
            cand,
            link_state=EntryLinkState.UNLINKED,
            schedule_task_id=None,
            last_synced_ms=new_synced_ms,
        )

    mig_match = find_migration_source(
        cand,
        working_entries=working_entries,
        unmatched_prev_entries=unmatched_prev_entries,
        handed_off_prev_ids=handed_off_prev_ids,
        working_external=working_external,
        effective_tasks=acc.effective_tasks,
    )
    if mig_match is not None:
        pool_name, pool_idx, src_entry = mig_match
        adopted_task_id = src_entry.schedule_task_id
        if adopted_task_id is not None and adopted_task_id in acc.effective_tasks:
            _retire_migration_source(
                pool_name,
                pool_idx,
                src_entry,
                sync_time_ms=sync_time_ms,
                working_entries=working_entries,
                handed_off_prev_ids=handed_off_prev_ids,
                working_external=working_external,
                external_dirty_indices=external_dirty_indices,
            )
            updated_ts = _apply_migration_handoff(
                cand,
                src_entry,
                adopted_task_id,
                acc,
                write_mod_ms=write_mod_ms,
                sync_time_ms=sync_time_ms,
            )
            return _build_synced_entry(
                cand,
                link_state=EntryLinkState.ACTIVE,
                schedule_task_id=adopted_task_id,
                last_synced_ms=max(new_synced_ms, updated_ts),
            )

    if item.task_state not in OPEN_TASK_STATES:
        return _build_synced_entry(
            cand,
            link_state=EntryLinkState.UNLINKED,
            schedule_task_id=None,
            last_synced_ms=new_synced_ms,
        )

    if has_newer_same_notebook_open_owner(cand, working_entries, acc.effective_tasks):
        return _build_synced_entry(
            cand,
            link_state=EntryLinkState.MIGRATED,
            schedule_task_id=None,
            last_synced_ms=new_synced_ms,
        )

    curr_title, curr_detail = format_task_title_and_detail(item.text, item.detail)
    task_id = acc.record_create(
        title=curr_title,
        detail=curr_detail,
        importance=expected_importance(item.is_starred),
        due_time=rp.page_date_ms,
        links=build_note_task_link(
            file_id=rp.file_id,
            file_path=rp.file_path,
            page_index=rp.page_index,
            page_id=rp.page_id,
            task_title=curr_title,
        ),
        modified_ms=write_mod_ms,
    )
    return _build_synced_entry(
        cand,
        link_state=EntryLinkState.ACTIVE,
        schedule_task_id=task_id,
        last_synced_ms=max(new_synced_ms, acc.effective_tasks[task_id].update_time),
    )


def plan_notebook_deletion(
    entries: Sequence[SyncedRapidLogEntry],
    remote_tasks: Mapping[str, RemoteTaskSnapshot],
) -> list[DeleteTaskAction]:
    """Plan `ScheduleTask` deletions when an entire `.note` file is deleted.

    Deletes still-open (`needsAction`) linked tasks while preserving `completed` tasks
    as historical records.
    """
    deletions: list[DeleteTaskAction] = []
    seen_task_ids: set[str] = set()
    for entry in entries:
        task_id = entry.schedule_task_id
        if (
            entry.link_state != EntryLinkState.ACTIVE
            or not task_id
            or task_id in seen_task_ids
        ):
            continue
        remote = remote_tasks.get(task_id)
        if remote is not None and remote.status != TaskStatus.COMPLETED:
            seen_task_ids.add(task_id)
            deletions.append(
                DeleteTaskAction(task_id=task_id, reason="notebook_deleted")
            )
    return deletions


def reconcile_rapid_log(
    *,
    file_id: int,
    file_path: str,
    pages: Sequence[NotebookPageInput],
    prev_entries: Sequence[SyncedRapidLogEntry],
    remote_tasks: Mapping[str, RemoteTaskSnapshot],
    sync_time_ms: int,
    external_entries: Sequence[SyncedRapidLogEntry] = (),
    task_id_factory: Callable[[], str] = _default_task_id_factory,
) -> ReconciliationPlan:
    """Reconcile a notebook's OCR pages against previous state and digital `ScheduleTask` snapshots."""
    chrono_pages = _resolve_pages(file_id, file_path, pages)
    prev_by_page, working_external, external_dirty_indices = _normalize_baselines(
        prev_entries, external_entries, remote_tasks, file_id
    )

    matched_pairs: list[tuple[ParsedCandidate, SyncedRapidLogEntry]] = []
    unmatched_new_candidates: list[ParsedCandidate] = []
    unmatched_prev_entries: list[SyncedRapidLogEntry] = []

    present_page_ids = {rp.page_id for rp in chrono_pages}
    for page_id, prev_list in prev_by_page.items():
        if page_id not in present_page_ids:
            unmatched_prev_entries.extend(prev_list)

    for rp in chrono_pages:
        m_pairs, u_new, u_prev = match_page_candidates(
            rp, prev_by_page.get(rp.page_id, [])
        )
        matched_pairs.extend(m_pairs)
        unmatched_new_candidates.extend(u_new)
        unmatched_prev_entries.extend(u_prev)

    acc = ActionAccumulator(remote_tasks, sync_time_ms, task_id_factory)

    working_entries = [
        _reconcile_matched_entry(cand, prev_entry, acc, sync_time_ms)
        for cand, prev_entry in matched_pairs
    ]

    handed_off_prev_ids: set[int] = set()
    ordered_new = sorted(
        unmatched_new_candidates,
        key=lambda c: (c.page.chrono_rank, c.raw_order),
    )
    for cand in ordered_new:
        working_entries.append(
            _reconcile_new_candidate(
                cand,
                working_entries=working_entries,
                unmatched_prev_entries=unmatched_prev_entries,
                handed_off_prev_ids=handed_off_prev_ids,
                working_external=working_external,
                external_dirty_indices=external_dirty_indices,
                acc=acc,
                sync_time_ms=sync_time_ms,
            )
        )

    active_owned_task_ids = {
        e.schedule_task_id
        for e in (*working_entries, *working_external)
        if e.link_state == EntryLinkState.ACTIVE and e.schedule_task_id is not None
    }
    for idx, prev_entry in enumerate(unmatched_prev_entries):
        task_id = prev_entry.schedule_task_id
        if (
            idx in handed_off_prev_ids
            or prev_entry.link_state != EntryLinkState.ACTIVE
            or task_id is None
            or task_id in active_owned_task_ids
        ):
            continue
        remote = acc.effective_tasks.get(task_id)
        if remote is not None and remote.status != TaskStatus.COMPLETED:
            acc.record_delete(task_id, reason="erased_from_page")

    working_entries.sort(key=lambda e: (e.page_index, e.page_id, e.item_order))
    updated_external = [working_external[i] for i in sorted(external_dirty_indices)]
    create_actions, update_actions, delete_actions = acc.finalize_actions(
        working_entries
    )

    return ReconciliationPlan(
        entries=working_entries,
        updated_external_entries=updated_external,
        create_tasks=create_actions,
        update_tasks=update_actions,
        delete_tasks=delete_actions,
    )
