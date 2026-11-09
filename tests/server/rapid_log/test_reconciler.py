"""End-to-end timeline scenarios for `supernote.server.rapid_log.reconciler`."""

from __future__ import annotations

from supernote.models.schedule import ScheduleTaskLinkDTO
from supernote.server.rapid_log import (
    EntryLinkState,
    NotebookPageInput,
    RemoteTaskSnapshot,
    SyncedRapidLogEntry,
    reconcile_rapid_log,
)
from supernote.server.utils.rapid_log import RapidLogKind, RapidLogTaskState
from tests.server.rapid_log.conftest import MagicTodoSimulator, make_page_id, utc_ms

# ==============================================================================
# Capture, Signifiers, Deep-Links & Pre-Completed History
# ==============================================================================


def test_capture_signifiers_details_events_notes_and_deep_links() -> None:
    sim = MagicTodoSimulator(start_time_ms=utc_ms(2026, 10, 26, 9, 30))
    sim.create_notebook(101, "/Note/Daily.note")
    p1 = make_page_id(2026, 10, 26, 9, 15, 30, "p1")

    sim.set_page(
        101,
        p1,
        """# 2026-10-26
* • Send Q3 architecture proposal
  - Include SQLite benchmark numbers
  - CC Alice
- [ ] Review PR #472
o 2pm Design sync with team
- Key takeaway: keep reconciler pure
""",
    )
    plan = sim.sync_notebook(101)

    assert len(plan.create_tasks) == 2
    assert len(sim.tasks) == 2

    t1 = sim.tasks["task-1"]
    assert t1.title == "Send Q3 architecture proposal"
    assert t1.importance == "high"
    assert t1.status == "needsAction"
    assert t1.detail == "- Include SQLite benchmark numbers\n- CC Alice"
    assert t1.due_time == utc_ms(2026, 10, 26)

    link1 = ScheduleTaskLinkDTO.from_b64(t1.links or "")
    assert link1.app_name == "Note"
    assert link1.path == "/Note/Daily.note"
    assert link1.file_id == "101"
    assert link1.page == 1
    assert link1.page_id == p1
    assert link1.task_title == "Send Q3 architecture proposal"

    t2 = sim.tasks["task-2"]
    assert t2.title == "Review PR #472"
    assert t2.importance == "normal"

    kinds = [(e.kind, e.link_state) for e in plan.entries]
    assert kinds == [
        (RapidLogKind.TASK, EntryLinkState.ACTIVE),
        (RapidLogKind.TASK, EntryLinkState.ACTIVE),
        (RapidLogKind.EVENT, EntryLinkState.UNLINKED),
        (RapidLogKind.NOTE, EntryLinkState.UNLINKED),
    ]


def test_pre_completed_historical_entry_ignored_until_reopened_in_ink(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(1, "/Note/Log.note")
    p1 = make_page_id(2026, 10, 26)

    simulator.set_page(1, p1, "X Had coffee with Sam\n• Draft agenda")
    plan1 = simulator.sync_notebook(1)
    assert [c.title for c in plan1.create_tasks] == ["Draft agenda"]

    simulator.advance(minutes=10)
    simulator.set_page(1, p1, "• Had coffee with Sam\n• Draft agenda")
    plan2 = simulator.sync_notebook(1)
    assert [c.title for c in plan2.create_tasks] == ["Had coffee with Sam"]
    assert len(simulator.tasks) == 2


# ==============================================================================
# Cross-Day & Cross-Notebook Migration Lifecycles (`>`, `<`, Implicit `•`)
# ==============================================================================


def test_sequential_migration_keeps_task_open_then_hands_off_to_next_day(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(10, "/Note/BuJo.note")
    mon = make_page_id(2026, 10, 26, 9, 0, 0, "mon")
    tue = make_page_id(2026, 10, 27, 9, 0, 0, "tue")

    simulator.set_page(10, mon, "• Renew passport\n  - Need 2x2 photo")
    simulator.sync_notebook(10)
    assert simulator.tasks["task-1"].due_time == utc_ms(2026, 10, 26)

    simulator.advance(hours=2)
    simulator.digital_edit("task-1", task_list_id="group-personal")

    # Monday evening: mark `>` BEFORE creating Tuesday's page -> stays open!
    simulator.advance(hours=9)
    simulator.set_page(10, mon, "> Renew passport\n  - Need 2x2 photo")
    plan_evening = simulator.sync_notebook(10)
    assert not plan_evening.has_task_mutations
    assert simulator.tasks["task-1"].status == "needsAction"

    # Tuesday morning: write `• Renew passport` on Tuesday's page
    simulator.advance(hours=13)
    simulator.set_page(10, tue, "• Renew passport\n  - Book USPS appointment")
    plan_tue = simulator.sync_notebook(10)

    assert plan_tue.create_tasks == []
    assert len(plan_tue.update_tasks) == 1
    t = simulator.tasks["task-1"]
    assert t.task_list_id == "group-personal"
    assert t.due_time == utc_ms(2026, 10, 27)
    assert t.detail == "- Need 2x2 photo\n- Book USPS appointment"
    link = ScheduleTaskLinkDTO.from_b64(t.links or "")
    assert link.page == 2
    assert link.page_id == tue

    entries = simulator.entries_by_file[10]
    assert (
        entries[0].page_id == mon and entries[0].link_state == EntryLinkState.MIGRATED
    )
    assert entries[1].page_id == tue and entries[1].link_state == EntryLinkState.ACTIVE


def test_single_sync_simultaneous_migration_and_multi_hop_chain(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(10, "/Note/BuJo.note")
    mon = make_page_id(2026, 10, 26, 9, 0)
    tue = make_page_id(2026, 10, 27, 9, 0)
    wed = make_page_id(2026, 10, 28, 9, 0)

    simulator.set_page(10, mon, "• File quarterly taxes")
    simulator.sync_notebook(10)

    simulator.advance(days=1)
    simulator.set_page(10, mon, "> File quarterly taxes")
    simulator.set_page(10, tue, "< File quarterly taxes")
    plan_d2 = simulator.sync_notebook(10)
    assert plan_d2.create_tasks == []
    assert len(plan_d2.update_tasks) == 1
    assert ScheduleTaskLinkDTO.from_b64(simulator.tasks["task-1"].links or "").page == 2

    simulator.advance(days=1)
    simulator.set_page(10, wed, "* • File quarterly taxes")
    simulator.sync_notebook(10)
    assert len(simulator.tasks) == 1
    assert simulator.tasks["task-1"].importance == "high"
    assert simulator.tasks["task-1"].due_time == utc_ms(2026, 10, 28)
    assert ScheduleTaskLinkDTO.from_b64(simulator.tasks["task-1"].links or "").page == 3

    simulator.advance(hours=4)
    simulator.set_page(10, wed, "* X File quarterly taxes")
    simulator.sync_notebook(10)
    assert simulator.tasks["task-1"].status == "completed"


def test_first_sync_offline_multi_page_migration_coalesces_into_single_create() -> None:
    sim = MagicTodoSimulator(start_time_ms=utc_ms(2026, 10, 27, 18, 0))
    sim.create_notebook(10, "/Note/Offline.note")
    mon = make_page_id(2026, 10, 26, 9, 0)
    tue = make_page_id(2026, 10, 27, 9, 0)

    sim.set_page(
        10, mon, "> Ship SDK\n> Fix login bug", modified_ms=utc_ms(2026, 10, 27, 9, 0)
    )
    sim.set_page(
        10, tue, "• Ship SDK\nX Fix login bug", modified_ms=utc_ms(2026, 10, 27, 17, 0)
    )

    plan = sim.sync_notebook(10)
    assert len(plan.create_tasks) == 2
    assert plan.update_tasks == []
    assert plan.delete_tasks == []

    ship = next(t for t in sim.tasks.values() if t.title == "Ship SDK")
    assert ship.status == "needsAction"
    assert ship.due_time == utc_ms(2026, 10, 27)
    assert ScheduleTaskLinkDTO.from_b64(ship.links or "").page_id == tue

    bug = next(t for t in sim.tasks.values() if t.title == "Fix login bug")
    assert bug.status == "completed"
    assert ScheduleTaskLinkDTO.from_b64(bug.links or "").page_id == tue


def test_out_of_order_implicit_migration_then_delayed_arrow_mark(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(10, "/Note/BuJo.note")
    mon = make_page_id(2026, 10, 26, 9, 0)
    tue = make_page_id(2026, 10, 27, 9, 0)

    simulator.set_page(10, mon, "• Book flights")
    simulator.sync_notebook(10)

    simulator.advance(days=1)
    simulator.set_page(10, tue, "• Book flights")
    plan_tue = simulator.sync_notebook(10)
    assert plan_tue.create_tasks == []
    assert (
        ScheduleTaskLinkDTO.from_b64(simulator.tasks["task-1"].links or "").page_id
        == tue
    )

    simulator.advance(hours=1)
    simulator.set_page(10, mon, "> Book flights")
    plan_backfill = simulator.sync_notebook(10)
    assert not plan_backfill.has_task_mutations


def test_reverse_chronological_and_mixed_cover_pages(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(1, "/Note/Hybrid.note")
    mon = make_page_id(2026, 10, 26, 9, 0)
    tue = make_page_id(2026, 10, 27, 9, 0)

    simulator.set_page(1, "TEMPLATE_COVER_0", "# 2026 Bullet Journal")
    simulator.set_page(1, mon, "• Setup backup")
    simulator.sync_notebook(1)

    # Prepend Tuesday right after cover (index 1, pushing Monday to index 2)
    simulator.advance(days=1)
    simulator.set_page(1, tue, "• Setup backup", insert_at=1)
    simulator.set_page(1, mon, "> Setup backup")
    plan = simulator.sync_notebook(1)

    assert plan.create_tasks == []
    link = ScheduleTaskLinkDTO.from_b64(simulator.tasks["task-1"].links or "")
    assert link.page == 2
    assert link.page_id == tue
    assert simulator.tasks["task-1"].due_time == utc_ms(2026, 10, 27)


def test_migration_preserves_custom_future_due_date_and_subnote_lifecycle(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(10, "/Note/BuJo.note")
    mon = make_page_id(2026, 10, 26, 9, 0)
    tue = make_page_id(2026, 10, 27, 9, 0)
    fri_deadline = utc_ms(2026, 10, 30, 17, 0)

    simulator.set_page(10, mon, "• Prepare board deck\n  - Revenue slide")
    simulator.sync_notebook(10)

    simulator.advance(hours=1)
    simulator.digital_edit("task-1", due_time=fri_deadline)

    simulator.advance(days=1)
    simulator.set_page(10, mon, "> Prepare board deck\n  - Revenue slide")
    simulator.set_page(10, tue, "• Prepare board deck\n  - Hiring plan slide")
    simulator.sync_notebook(10)

    t = simulator.tasks["task-1"]
    assert t.due_time == fri_deadline
    assert t.detail == "- Revenue slide\n- Hiring plan slide"

    # Add a third sub-bullet on Tuesday
    simulator.advance(hours=2)
    simulator.set_page(
        10, tue, "• Prepare board deck\n  - Hiring plan slide\n  - Appendix metrics"
    )
    simulator.sync_notebook(10)
    assert (
        simulator.tasks["task-1"].detail
        == "- Revenue slide\n- Hiring plan slide\n- Appendix metrics"
    )

    # Erase Tuesday's sub-notes -> Monday's migrated note still survives!
    simulator.advance(hours=1)
    simulator.set_page(10, tue, "• Prepare board deck")
    simulator.sync_notebook(10)
    assert simulator.tasks["task-1"].detail == "- Revenue slide"


def test_cross_notebook_migration_requires_explicit_arrow_preventing_false_steals() -> (
    None
):
    sim = MagicTodoSimulator(start_time_ms=utc_ms(2026, 10, 31, 9, 0))
    sim.create_notebook(1, "/Note/Oct-2026.note")
    sim.create_notebook(2, "/Note/Nov-2026.note")
    sim.create_notebook(3, "/Note/Home.note")

    oct31 = make_page_id(2026, 10, 31, 9, 0)
    nov01 = make_page_id(2026, 11, 1, 9, 0)
    home1 = make_page_id(2026, 11, 1, 10, 0)

    sim.set_page(1, oct31, "• Renew lease\n• Check mailbox")
    sim.sync_notebook(1)

    # Independent Home.note `• Check mailbox` does NOT steal Oct-2026's unmigrated task
    sim.advance(days=1)
    sim.set_page(3, home1, "• Check mailbox")
    plan_home = sim.sync_notebook(3)
    assert len(plan_home.create_tasks) == 1

    # Explicit `> Renew lease` in Oct-2026 hands off cleanly to Nov-2026
    sim.advance(hours=1)
    sim.set_page(1, oct31, "> Renew lease\n• Check mailbox")
    sim.sync_notebook(1)

    sim.set_page(2, nov01, "• Renew lease")
    plan_nov = sim.sync_notebook(2)
    assert plan_nov.create_tasks == []
    assert len(plan_nov.update_tasks) == 1
    assert len(plan_nov.updated_external_entries) == 1

    link = ScheduleTaskLinkDTO.from_b64(sim.tasks["task-1"].links or "")
    assert link.file_id == "2"
    assert link.path == "/Note/Nov-2026.note"
    assert sim.entries_by_file[1][0].link_state == EntryLinkState.MIGRATED


# ==============================================================================
# 3-Way Conflicts, Timestamps, Recurring Chores & Deletions
# ==============================================================================


def test_completed_task_in_ink_or_digital_does_not_get_hijacked_by_later_chore(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(1, "/Note/Chores.note")
    mon = make_page_id(2026, 10, 26, 9, 0)
    fri = make_page_id(2026, 10, 30, 9, 0)

    simulator.set_page(1, mon, "• Buy groceries\n• Water plants")
    simulator.sync_notebook(1)

    simulator.advance(hours=3)
    simulator.set_page(1, mon, "X Buy groceries\n• Water plants")
    simulator.sync_notebook(1)
    simulator.advance(hours=1)
    simulator.digital_complete("task-2")

    simulator.advance(days=4)
    simulator.set_page(1, fri, "• Buy groceries\n• Water plants")
    plan_fri = simulator.sync_notebook(1)
    assert len(plan_fri.create_tasks) == 2
    assert simulator.tasks["task-1"].status == "completed"
    assert simulator.tasks["task-2"].status == "completed"
    assert simulator.tasks["task-3"].status == "needsAction"
    assert simulator.tasks["task-4"].status == "needsAction"


def test_digital_completion_reopen_and_completed_time_preservation(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(1, "/Note/Work.note")
    p1 = make_page_id(2026, 10, 26, 9, 0)

    simulator.set_page(1, p1, "• Call Bob\n• Write spec")
    simulator.sync_notebook(1)

    done_ts = simulator.advance(hours=1)
    simulator.digital_complete("task-1", at_ms=done_ts)

    simulator.advance(hours=2)
    simulator.set_page(1, p1, "• Call Bob\nX Write spec\n• Book room")
    simulator.sync_notebook(1)

    assert simulator.tasks["task-1"].status == "completed"
    assert simulator.tasks["task-2"].status == "completed"

    # Drawing `X` later on "Call Bob" to match digital check-off preserves `done_ts`!
    simulator.advance(hours=1)
    simulator.set_page(1, p1, "X Call Bob\nX Write spec\n• Book room")
    plan_catchup = simulator.sync_notebook(1)
    assert plan_catchup.update_tasks == []
    assert simulator.tasks["task-1"].completed_time == done_ts

    # Reopening "Write spec" digitally survives unrelated page edits
    simulator.advance(hours=1)
    simulator.digital_reopen("task-2")
    simulator.advance(hours=1)
    simulator.set_page(
        1, p1, "X Call Bob\nX Write spec\n• Book room\n- Extra meeting note"
    )
    simulator.sync_notebook(1)
    assert simulator.tasks["task-2"].status == "needsAction"


def test_simultaneous_conflict_uses_timestamps_and_settles_idempotently(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(1, "/Note/Work.note")
    p1 = make_page_id(2026, 10, 26, 9, 0)

    simulator.set_page(1, p1, "* • Audit server logs")
    simulator.sync_notebook(1)
    audit_id = "task-1"

    # Case A: Older offline ink edit at t+10m vs newer digital edits at t+30m -> Digital wins!
    t_ink_older = simulator.advance(minutes=10)
    t_digital_newer = simulator.advance(minutes=20)
    simulator.digital_edit(
        audit_id,
        importance="low",
        title="Audit production logs",
        at_ms=t_digital_newer,
    )
    simulator.set_page(1, p1, "• Audit server logs soon", modified_ms=t_ink_older)
    sync_ts = simulator.advance(minutes=5)
    simulator.sync_notebook(1, sync_time_ms=sync_ts)
    assert simulator.tasks[audit_id].importance == "low"
    assert simulator.tasks[audit_id].title == "Audit production logs"

    # Case B: Newer ink edit at t+65m > t+30m -> Notebook wins!
    t_ink_newer = simulator.advance(minutes=30)
    simulator.set_page(
        1, p1, "* • Audit server logs soon with Alice", modified_ms=t_ink_newer
    )
    simulator.sync_notebook(1, sync_time_ms=t_ink_newer)
    assert simulator.tasks[audit_id].importance == "high"
    assert simulator.tasks[audit_id].title == "Audit server logs soon with Alice"


def test_orthogonal_field_edits_do_not_block_or_clobber_each_other(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(1, "/Note/Work.note")
    p1 = make_page_id(2026, 10, 26, 9, 0)

    simulator.set_page(1, p1, "• Review contract")
    simulator.sync_notebook(1)

    t_ink = simulator.advance(minutes=15)
    t_digital = simulator.advance(minutes=15)
    custom_due = utc_ms(2026, 11, 5)

    simulator.digital_edit(
        "task-1",
        due_time=custom_due,
        task_list_id="group-legal",
        detail="Check indemnity clause",
        at_ms=t_digital,
    )
    simulator.set_page(1, p1, "* • Review contract", modified_ms=t_ink)

    simulator.advance(minutes=5)
    simulator.sync_notebook(1)

    t = simulator.tasks["task-1"]
    assert t.importance == "high"
    assert t.due_time == custom_due
    assert t.task_list_id == "group-legal"
    assert t.detail == "Check indemnity clause"


def test_digital_deletion_tombstone_and_explicit_revival(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(1, "/Note/Daily.note")
    p1 = make_page_id(2026, 10, 26, 9, 0)
    p0_cover = make_page_id(2026, 10, 25, 9, 0)
    p2_next = make_page_id(2026, 10, 27, 9, 0)

    simulator.set_page(1, p1, "• Call Bob\n• Clean garage")
    simulator.sync_notebook(1)
    simulator.advance(minutes=5)
    simulator.set_page(1, p1, "• Call Bob\nX Clean garage")
    simulator.sync_notebook(1)

    # User deletes both tasks in the To-Do app
    simulator.advance(minutes=5)
    simulator.digital_delete("task-1")
    simulator.digital_delete("task-2")

    # Adding sub-notes, inserting a cover page, and renaming notebook does NOT resurrect unchanged `• Call Bob`
    simulator.advance(minutes=10)
    simulator.set_page(1, p0_cover, "# Cover", insert_at=0)
    simulator.set_page(1, p1, "• Call Bob\n  - Left voicemail\nX Clean garage")
    simulator.rename_notebook(1, "/Note/RenamedDaily.note")
    plan = simulator.sync_notebook(1)
    assert plan.create_tasks == []
    assert simulator.tasks == {}

    # Explicitly reopening `X Clean garage` -> `• Clean garage` on p1 OR writing `• Call Bob` on p2 creates fresh tasks!
    simulator.advance(days=1)
    simulator.set_page(1, p1, "• Call Bob\n  - Left voicemail\n• Clean garage")
    simulator.set_page(1, p2_next, "• Call Bob")
    plan_revive = simulator.sync_notebook(1)
    assert [c.title for c in plan_revive.create_tasks] == ["Clean garage", "Call Bob"]


def test_strikethrough_cancellation_lasso_moves_and_notebook_deletion(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(1, "/Note/Daily.note")
    p1 = make_page_id(2026, 10, 26, 9, 0)
    p2 = make_page_id(2026, 10, 27, 9, 0)

    # Prose strikethrough ignored; tasks created
    simulator.set_page(
        1,
        p1,
        "~~Random scratched sentence~~\n• Strike me\n• Move me\n• Erase me\n• Done keep me",
    )
    simulator.sync_notebook(1)
    simulator.advance(minutes=5)
    simulator.digital_edit("task-2", task_list_id="group-vip")
    simulator.digital_complete("task-4")

    # Strike out task-1 (`~~Strike me~~`), lasso-move task-2 to p2, and erase task-3!
    simulator.advance(days=1)
    simulator.set_page(1, p1, "~~Strike me~~")
    simulator.set_page(1, p2, "• Move me\n• Open on p2")
    plan = simulator.sync_notebook(1)

    assert [c.title for c in plan.create_tasks] == ["Open on p2"]
    assert {d.task_id for d in plan.delete_tasks} == {"task-1", "task-3"}
    assert simulator.tasks["task-2"].task_list_id == "group-vip"
    assert (
        ScheduleTaskLinkDTO.from_b64(simulator.tasks["task-2"].links or "").page_id
        == p2
    )
    assert simulator.tasks["task-4"].status == "completed"

    # Un-striking `• Strike me` revives a fresh open task
    simulator.advance(minutes=10)
    simulator.set_page(1, p1, "• Strike me")
    plan_unstruck = simulator.sync_notebook(1)
    assert [c.title for c in plan_unstruck.create_tasks] == ["Strike me"]

    # Deleting the entire notebook deletes open tasks, keeping completed task-4
    deleted = simulator.delete_notebook(1)
    assert set(deleted) == {"task-6", "task-2", "task-5"}
    assert set(simulator.tasks) == {"task-4"}


def test_entry_id_propagated_across_matched_and_external_entries() -> None:
    mon = make_page_id(2026, 10, 26, 9, 0)
    tue = make_page_id(2026, 10, 27, 9, 0)

    ext_entry = SyncedRapidLogEntry(
        file_id=1,
        file_path="/Note/Oct.note",
        page_id=mon,
        page_index=0,
        item_order=0,
        occurrence_index=0,
        kind=RapidLogKind.TASK,
        normalized_text="renew domain",
        text="Renew domain",
        task_state=RapidLogTaskState.MIGRATED_FORWARD,
        link_state=EntryLinkState.ACTIVE,
        schedule_task_id="t-100",
        last_synced_ms=1000,
        entry_id=9001,
    )
    local_prev = SyncedRapidLogEntry(
        file_id=2,
        file_path="/Note/Nov.note",
        page_id=tue,
        page_index=0,
        item_order=0,
        occurrence_index=0,
        kind=RapidLogKind.NOTE,
        normalized_text="kickoff note",
        text="Kickoff note",
        link_state=EntryLinkState.UNLINKED,
        last_synced_ms=1000,
        entry_id=9002,
    )
    remote = {
        "t-100": RemoteTaskSnapshot(
            task_id="t-100",
            title="Renew domain",
            status="needsAction",
            update_time=1000,
        )
    }

    plan = reconcile_rapid_log(
        file_id=2,
        file_path="/Note/Nov.note",
        pages=[
            NotebookPageInput(
                page_id=tue,
                page_index=0,
                text_content="- Kickoff note\n• Renew domain",
                page_modified_ms=2000,
            )
        ],
        prev_entries=[local_prev],
        remote_tasks=remote,
        sync_time_ms=2000,
        external_entries=[ext_entry],
    )

    assert plan.entries[0].entry_id == 9002
    assert plan.entries[1].entry_id is None
    assert len(plan.updated_external_entries) == 1
    assert plan.updated_external_entries[0].entry_id == 9001
    assert plan.updated_external_entries[0].link_state == EntryLinkState.MIGRATED


# ==============================================================================
# Adversarial Edge-Case Regressions
# ==============================================================================


def test_offline_implicit_dot_then_explicit_arrow_keeps_chronological_anchor() -> None:
    """Monday `• Ship v2` + Tuesday `> Ship v2` synced offline anchors on Tuesday, not Monday."""
    sim = MagicTodoSimulator(start_time_ms=utc_ms(2026, 10, 27, 20, 0))
    sim.create_notebook(1, "/Note/BuJo.note")
    mon = make_page_id(2026, 10, 26, 9, 0)
    tue = make_page_id(2026, 10, 27, 9, 0)

    sim.set_page(1, mon, "• Ship v2", modified_ms=utc_ms(2026, 10, 26, 9, 0))
    sim.set_page(1, tue, "> Ship v2", modified_ms=utc_ms(2026, 10, 27, 19, 0))
    plan = sim.sync_notebook(1)

    assert len(plan.create_tasks) == 1
    assert ScheduleTaskLinkDTO.from_b64(sim.tasks["task-1"].links or "").page_id == tue
    assert [e.link_state for e in sim.entries_by_file[1]] == [
        EntryLinkState.MIGRATED,
        EntryLinkState.ACTIVE,
    ]


def test_late_sync_of_older_page_does_not_hijack_newer_active_task_backward(
    simulator: MagicTodoSimulator,
) -> None:
    """Syncing Tuesday first and Monday second converges identically to Monday then Tuesday."""
    simulator.create_notebook(1, "/Note/BuJo.note")
    mon = make_page_id(2026, 10, 26, 9, 0)
    tue = make_page_id(2026, 10, 27, 9, 0)

    # Tuesday syncs FIRST
    simulator.set_page(1, tue, "• Weekly standup")
    simulator.sync_notebook(1)
    assert (
        ScheduleTaskLinkDTO.from_b64(simulator.tasks["task-1"].links or "").page_id
        == tue
    )

    # Monday page is inserted/OCR'd LATER at index 0 with the same open bullet
    simulator.advance(minutes=15)
    simulator.set_page(1, mon, "• Weekly standup", insert_at=0)
    plan_late_mon = simulator.sync_notebook(1)

    # No duplicate task created, and Tuesday retains ownership (only page index 1->2 link updated)
    assert plan_late_mon.create_tasks == []
    assert len(simulator.tasks) == 1
    link = ScheduleTaskLinkDTO.from_b64(simulator.tasks["task-1"].links or "")
    assert link.page_id == tue
    assert link.page == 2
    assert simulator.tasks["task-1"].due_time == utc_ms(2026, 10, 27)
    assert [(e.page_id, e.link_state) for e in simulator.entries_by_file[1]] == [
        (mon, EntryLinkState.MIGRATED),
        (tue, EntryLinkState.ACTIVE),
    ]


def test_zero_page_modified_ms_loses_conflict_tie_against_timestamped_digital_edit(
    simulator: MagicTodoSimulator,
) -> None:
    """Unknown `page_modified_ms == 0` must not use `sync_time_ms` to clobber digital edits."""
    simulator.create_notebook(1, "/Note/Legacy.note")
    p1 = make_page_id(2026, 10, 26, 9, 0)

    simulator.set_page(1, p1, "• Call Bob about roadmap", modified_ms=0)
    simulator.sync_notebook(1)

    t_digital = simulator.advance(minutes=30)
    simulator.digital_edit("task-1", title="Call Bob (confirmed)", at_ms=t_digital)

    # OCR re-runs at t+60m with `page_modified_ms=0` and OCR jitter -> digital edit wins!
    sync_ts = simulator.advance(minutes=30)
    simulator.set_page(1, p1, "• Call B0b about roadmap", modified_ms=0)
    plan = simulator.sync_notebook(1, sync_time_ms=sync_ts)

    assert plan.update_tasks == []
    assert simulator.tasks["task-1"].title == "Call Bob (confirmed)"


def test_digital_title_rename_does_not_emit_spurious_anchor_update_on_unchanged_sync(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(1, "/Note/Daily.note")
    p1 = make_page_id(2026, 10, 26, 9, 0)

    simulator.set_page(1, p1, "• Call Bob")
    simulator.sync_notebook(1)

    edit_ts = simulator.advance(minutes=15)
    simulator.digital_edit("task-1", title="Call Bob (555-0199)", at_ms=edit_ts)

    # Subsequent unchanged notebook sync emits zero updates and preserves digital update_time
    simulator.advance(minutes=45)
    plan = simulator.sync_notebook(1)
    assert not plan.has_task_mutations
    assert simulator.tasks["task-1"].update_time == edit_ts


def test_migrating_forward_then_crossing_out_on_destination_page_cancels_open_task(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(1, "/Note/BuJo.note")
    mon = make_page_id(2026, 10, 26, 9, 0)
    tue = make_page_id(2026, 10, 27, 9, 0)

    simulator.set_page(1, mon, "• Call vendor")
    simulator.sync_notebook(1)

    # User migrates `> Call vendor` on Monday, writes `• Call vendor` on Tuesday, then strikes it out
    simulator.advance(days=1)
    simulator.set_page(1, mon, "> Call vendor")
    simulator.set_page(1, tue, "~~• Call vendor~~")
    plan = simulator.sync_notebook(1)

    assert [d.task_id for d in plan.delete_tasks] == ["task-1"]
    assert simulator.tasks == {}
    assert [(e.page_id, e.link_state) for e in simulator.entries_by_file[1]] == [
        (mon, EntryLinkState.MIGRATED),
        (tue, EntryLinkState.CANCELLED_INK),
    ]

    # Un-striking `• Call vendor` on Tuesday cleanly creates a fresh task
    simulator.advance(minutes=10)
    simulator.set_page(1, tue, "• Call vendor")
    plan_revive = simulator.sync_notebook(1)
    assert [c.title for c in plan_revive.create_tasks] == ["Call vendor"]


def test_self_heals_duplicate_active_owners_without_deleting_live_task() -> None:
    mon = make_page_id(2026, 10, 26, 9, 0)
    tue = make_page_id(2026, 10, 27, 9, 0)

    stale_mon = SyncedRapidLogEntry(
        file_id=1,
        file_path="/Note/BuJo.note",
        page_id=mon,
        page_index=0,
        item_order=0,
        occurrence_index=0,
        kind=RapidLogKind.TASK,
        normalized_text="ship release",
        text="Ship release",
        task_state=RapidLogTaskState.MIGRATED_FORWARD,
        page_created_ms=utc_ms(2026, 10, 26, 9, 0),
        link_state=EntryLinkState.ACTIVE,
        schedule_task_id="t-live",
        last_synced_ms=1000,
    )
    live_tue = SyncedRapidLogEntry(
        file_id=1,
        file_path="/Note/BuJo.note",
        page_id=tue,
        page_index=1,
        item_order=0,
        occurrence_index=0,
        kind=RapidLogKind.TASK,
        normalized_text="ship release",
        text="Ship release",
        task_state=RapidLogTaskState.INCOMPLETE,
        page_created_ms=utc_ms(2026, 10, 27, 9, 0),
        link_state=EntryLinkState.ACTIVE,
        schedule_task_id="t-live",
        last_synced_ms=2000,
    )
    remote = {
        "t-live": RemoteTaskSnapshot(
            task_id="t-live",
            title="Ship release",
            status="needsAction",
            update_time=2000,
        )
    }

    # Monday page is removed while Tuesday remains -> t-live MUST NOT be deleted!
    plan = reconcile_rapid_log(
        file_id=1,
        file_path="/Note/BuJo.note",
        pages=[
            NotebookPageInput(
                page_id=tue,
                page_index=0,
                text_content="• Ship release",
                page_modified_ms=2000,
            )
        ],
        prev_entries=[stale_mon, live_tue],
        remote_tasks=remote,
        sync_time_ms=3000,
    )

    assert plan.delete_tasks == []
    assert len(plan.entries) == 1
    assert plan.entries[0].link_state == EntryLinkState.ACTIVE
    assert plan.entries[0].schedule_task_id == "t-live"
