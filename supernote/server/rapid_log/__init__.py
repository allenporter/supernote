"""Bullet Journal Rapid Logging lifecycle and reconciliation package.

Overview
--------
This package implements the pure, deterministic state machine that bridges
handwritten Bullet Journal Rapid Logging pages (extracted from OCR Markdown)
with digital tasks in `ScheduleService`:

1. **Input Snapshot**: Callers supply the current notebook's OCR pages
   (`NotebookPageInput`), previously persisted bullet baselines
   (`SyncedRapidLogEntry` for this notebook and any external migration
   candidates), and live digital task snapshots (`RemoteTaskSnapshot`).
2. **Pure Planning**: `reconcile_rapid_log` (and `plan_notebook_deletion` when
   an entire `.note` file is deleted) computes a `ReconciliationPlan` containing
   the next baseline entries plus minimal, disjoint `CreateTaskAction`,
   `UpdateTaskAction`, and `DeleteTaskAction` commands with encoded
   notebook/page deep-links.
3. **Storage & Queue Independence**: None of the modules in this package import
   database models, sessions, or background processor queues, keeping domain
   rules fast to test and decoupled from persistence mechanics.

Module Layout
-------------
- `models`: Immutable input/output contracts and `EntryLinkState`.
- `formatting`: Text normalization, `P<YYYYMMDDHHMMSS>` page creation timestamp
  parsing, `ScheduleTaskLinkDTO` deep-link encoding, safe title truncation, and
  prefix-preserving cross-page detail merging.
- `matching`: Two-pass in-page bullet identity matching (`match_page_candidates`,
  exact occurrence pairing plus bounded OCR jitter / word-extension matching)
  and chronological migration selection (`find_migration_source`).
- `actions`: Same-sync action coalescing (`ActionAccumulator`) preserving visual
  page/line creation order.
- `reconciler`: 3-way timestamp planner (`reconcile_rapid_log` and
  `plan_notebook_deletion`).

State-Machine Principles & Invariants
-------------------------------------
1. **Explicit Link Lifecycle (`EntryLinkState`)**:
   Every bullet tracks its relationship to `ScheduleService` explicitly
   (`UNLINKED`, `ACTIVE`, `MIGRATED`, `CANCELLED_INK`, `DISMISSED_DIGITAL`)
   rather than inferring sync state from raw ink alone.
2. **Edge-Triggered 3-Way Field Reconciliation**:
   Each mutable field (`status`, `importance`, `title`, `detail`) is diffed
   independently across `(previous_entry, current_item, remote_task)`.
   Unchanged ink never overwrites manual digital To-Do edits (such as checking
   off a task in the app, changing priority, editing notes, setting a due date,
   or moving lists). When both ink and the digital task modified the *same*
   field since the last sync, `page_modified_ms >= remote_task.update_time`
   breaks the tie deterministically.
3. **Continuous Task Identity Across Migrations**:
   Marking a bullet `>` or `<` keeps its digital task open (`needsAction`).
   Rewriting `•` on a newer page—or lasso-moving a bullet within the notebook,
   or rewriting `•` in another notebook after an explicit `>` / `<` arrow—hands
   off the existing `ScheduleTask` (transitioning the source entry to
   `MIGRATED`), advancing its page deep-link and default `due_time` while
   preserving custom future due dates, task list placement, and accumulated
   sub-bullet context.
4. **Historical Finality & Pre-Completed Filtering**:
   Bullets first observed as already completed (`X`) remain `UNLINKED` so
   historical logs never clutter the To-Do list. Conversely, once a linked task
   is `completed` (in ink or digitally), erasing the bullet, crossing it out,
   or deleting the notebook preserves the completed digital record, and future
   same-named chores create fresh tasks instead of hijacking completed ones.
5. **Tombstoning Manual Digital Deletions (`DISMISSED_DIGITAL`)**:
   If a user deletes an `ACTIVE` task in the To-Do app, its bullet entry
   transitions to `DISMISSED_DIGITAL` so subsequent page re-syncs, sub-note
   edits, or page shifts never resurrect a zombie task unless the bullet is
   explicitly completed and later reopened in ink (`X` -> `•`).
6. **Strict Idempotency & Disjoint Actions**:
   Applying a `ReconciliationPlan` and immediately re-running
   `reconcile_rapid_log` with no intervening ink or digital mutations produces
   zero create, update, or delete actions, and multi-hop changes within a
   single sync coalesce into at most one net action per task.
"""

from supernote.server.rapid_log.formatting import (
    build_note_task_link,
    format_task_title_and_detail,
    infer_page_created_ms,
    infer_page_date_ms,
    normalize_rapid_log_text,
)
from supernote.server.rapid_log.models import (
    MAX_TASK_DETAIL_LENGTH,
    MAX_TASK_TITLE_LENGTH,
    CreateTaskAction,
    DeleteTaskAction,
    EntryLinkState,
    NotebookPageInput,
    ReconciliationPlan,
    RemoteTaskSnapshot,
    SyncedRapidLogEntry,
    TaskImportance,
    TaskStatus,
    UpdateTaskAction,
)
from supernote.server.rapid_log.reconciler import (
    plan_notebook_deletion,
    reconcile_rapid_log,
)

__all__ = [
    "CreateTaskAction",
    "DeleteTaskAction",
    "EntryLinkState",
    "MAX_TASK_DETAIL_LENGTH",
    "MAX_TASK_TITLE_LENGTH",
    "NotebookPageInput",
    "ReconciliationPlan",
    "RemoteTaskSnapshot",
    "SyncedRapidLogEntry",
    "TaskImportance",
    "TaskStatus",
    "UpdateTaskAction",
    "build_note_task_link",
    "format_task_title_and_detail",
    "infer_page_created_ms",
    "infer_page_date_ms",
    "normalize_rapid_log_text",
    "plan_notebook_deletion",
    "reconcile_rapid_log",
]
