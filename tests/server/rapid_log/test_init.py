"""Tests for `supernote.server.rapid_log` package exports and docstring contract."""

from __future__ import annotations

import supernote.server.rapid_log as rapid_log


def test_rapid_log_package_exports_and_docstring() -> None:
    expected_exports = {
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
    }
    assert set(rapid_log.__all__) == expected_exports
    for symbol in expected_exports:
        assert hasattr(rapid_log, symbol)
    assert rapid_log.__doc__ is not None
    assert "State-Machine Principles & Invariants" in rapid_log.__doc__
