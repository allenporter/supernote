"""Unit tests for `supernote.server.rapid_log.actions`."""

from __future__ import annotations

from supernote.server.rapid_log.actions import ActionAccumulator
from supernote.server.rapid_log.models import (
    EntryLinkState,
    RemoteTaskSnapshot,
    SyncedRapidLogEntry,
)
from supernote.server.utils.rapid_log import RapidLogKind
from tests.server.rapid_log.conftest import MagicTodoSimulator, make_page_id


def test_accumulator_coalesces_create_then_update_and_create_then_delete() -> None:
    seq = iter(["t-1", "t-2"])
    orig = {
        "existing-1": RemoteTaskSnapshot(
            task_id="existing-1",
            title="Keep me",
            detail="",
            status="needsAction",
            importance="normal",
            update_time=100,
        )
    }
    acc = ActionAccumulator(orig, sync_time_ms=500, task_id_factory=lambda: next(seq))

    # Create t-1, then update t-1 in the same batch -> folded into single CreateTaskAction
    tid1 = acc.record_create(
        title="Draft memo",
        detail="",
        importance="normal",
        due_time=None,
        links="link-p1",
        modified_ms=500,
    )
    acc.record_update(
        tid1,
        {"importance": "high", "links": "link-p2"},
        reason="migrated_handoff",
        modified_ms=510,
    )

    # Create t-2, then delete t-2 in the same batch -> completely cancelled out
    tid2 = acc.record_create(
        title="Transient",
        detail="",
        importance="normal",
        due_time=None,
        links="link-p1",
        modified_ms=500,
    )
    acc.record_delete(tid2, reason="cancelled_ink")

    # Update existing-1 to a different value, then revert back to original -> stripped as net no-op
    acc.record_update(
        "existing-1", {"importance": "high"}, reason="star", modified_ms=500
    )
    acc.record_update(
        "existing-1", {"importance": "normal"}, reason="unstar", modified_ms=505
    )

    entries = [
        SyncedRapidLogEntry(
            file_id=1,
            file_path="/Note/A.note",
            page_id="p2",
            page_index=1,
            item_order=0,
            occurrence_index=0,
            kind=RapidLogKind.TASK,
            normalized_text="draft memo",
            text="Draft memo",
            link_state=EntryLinkState.ACTIVE,
            schedule_task_id="t-1",
        )
    ]
    creates, updates, deletes = acc.finalize_actions(entries)
    assert len(creates) == 1
    assert creates[0].task_id == "t-1"
    assert creates[0].importance == "high"
    assert creates[0].links == "link-p2"
    assert updates == []
    assert deletes == []


def test_visual_create_order_preserved_when_migrated_arrows_mixed_with_dots(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(1, "/Note/Daily.note")
    p1 = make_page_id(2026, 10, 26, 9, 0)

    simulator.set_page(
        1, p1, "• First bullet\n> Second migrated bullet\n• Third bullet"
    )
    plan = simulator.sync_notebook(1)

    assert [(c.order_hint, c.title) for c in plan.create_tasks] == [
        (0, "First bullet"),
        (1, "Second migrated bullet"),
        (2, "Third bullet"),
    ]
