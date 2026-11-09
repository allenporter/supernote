"""Unit tests for `supernote.server.rapid_log.models`."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, cast

import pytest

from supernote.server.rapid_log.models import (
    DeleteTaskAction,
    EntryLinkState,
    NotebookPageInput,
    ReconciliationPlan,
    RemoteTaskSnapshot,
    TaskImportance,
    TaskStatus,
    UpdateTaskAction,
)


def test_enums_and_default_snapshots() -> None:
    assert TaskStatus.NEEDS_ACTION == "needsAction"
    assert TaskStatus.COMPLETED == "completed"
    assert TaskImportance.NORMAL == "normal"
    assert TaskImportance.HIGH == "high"
    assert EntryLinkState.DISMISSED_DIGITAL == "DISMISSED_DIGITAL"

    snap = RemoteTaskSnapshot(task_id="t-1", title="Check logs")
    assert snap.status == TaskStatus.NEEDS_ACTION

    page = NotebookPageInput(page_id="P20261026090000abc", page_index=0)
    assert page.page_modified_ms == 0
    assert page.text_content is None


def test_update_task_action_freezes_updates_mapping() -> None:
    raw_updates = {"title": "New title", "importance": TaskImportance.HIGH}
    action = UpdateTaskAction(task_id="t-1", updates=raw_updates, reason="ink_title")

    # Mutating caller's input dict does not affect frozen UpdateTaskAction
    raw_updates["title"] = "Tampered"
    assert isinstance(action.updates, MappingProxyType)
    assert action.updates == {"title": "New title", "importance": "high"}

    with pytest.raises(TypeError):
        cast(Any, action.updates)["title"] = "Mutated"


def test_reconciliation_plan_has_task_mutations_property() -> None:
    empty = ReconciliationPlan(entries=[])
    assert not empty.has_task_mutations

    with_delete = ReconciliationPlan(
        entries=[],
        delete_tasks=[DeleteTaskAction(task_id="t-1", reason="erased_from_page")],
    )
    assert with_delete.has_task_mutations
