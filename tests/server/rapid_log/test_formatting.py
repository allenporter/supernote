"""Unit tests for `supernote.server.rapid_log.formatting`."""

from __future__ import annotations

from supernote.models.schedule import ScheduleTaskLinkDTO
from supernote.server.rapid_log import (
    MAX_TASK_TITLE_LENGTH,
    build_note_task_link,
    format_task_title_and_detail,
    infer_page_created_ms,
    infer_page_date_ms,
    normalize_rapid_log_text,
)
from supernote.server.rapid_log.formatting import (
    field_values_differ,
    merge_migrated_detail,
)
from tests.server.rapid_log.conftest import MagicTodoSimulator, make_page_id, utc_ms


def test_normalize_rapid_log_text_collapses_whitespace_and_case() -> None:
    assert normalize_rapid_log_text("  Send   Q3\tProposal  ") == "send q3 proposal"


def test_page_timestamp_inference_precision_and_invalid_ids() -> None:
    pid_full = "P20261108143522xyz"
    assert infer_page_date_ms(pid_full) == utc_ms(2026, 11, 8, 0, 0, 0)
    assert infer_page_created_ms(pid_full) == utc_ms(2026, 11, 8, 14, 35, 22)

    pid_date_only = "P20261108_custom"
    assert infer_page_date_ms(pid_date_only) == utc_ms(2026, 11, 8, 0, 0, 0)
    assert infer_page_created_ms(pid_date_only) == utc_ms(2026, 11, 8, 0, 0, 0)

    # Invalid HMS digits fall back to valid date prefix
    assert infer_page_created_ms("P20261108999999xyz") == utc_ms(2026, 11, 8, 0, 0, 0)
    assert infer_page_date_ms("custom_page_1") is None
    assert infer_page_created_ms("P20261399") is None
    assert infer_page_date_ms("") is None


def test_overlong_title_safely_truncated_and_migrated_without_duplicating_headline(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(1, "/Note/Verbose.note")
    p1 = make_page_id(2026, 10, 26)
    p2 = make_page_id(2026, 10, 27)

    long_sentence = "Investigate " + ("very-detailed-corner-case " * 15) + "end"
    assert len(long_sentence) > MAX_TASK_TITLE_LENGTH

    simulator.set_page(1, p1, f"• {long_sentence}\n  - Extra sub-bullet context")
    simulator.sync_notebook(1)

    t1 = simulator.tasks["task-1"]
    assert len(t1.title) <= MAX_TASK_TITLE_LENGTH
    assert t1.title.endswith("…")
    assert t1.detail == f"{long_sentence}\n\n- Extra sub-bullet context"

    # Migrate overlong bullet to p2 with a new sub-bullet -> headline appears only ONCE
    simulator.advance(days=1)
    simulator.set_page(1, p1, f"> {long_sentence}\n  - Extra sub-bullet context")
    simulator.set_page(1, p2, f"• {long_sentence}\n  - Follow-up note")
    simulator.sync_notebook(1)

    assert simulator.tasks["task-1"].detail == (
        f"{long_sentence}\n\n- Extra sub-bullet context\n- Follow-up note"
    )

    # Direct cap test on `max_detail_length`
    title, capped_detail = format_task_title_and_detail(
        "Short", "x" * 100, max_detail_length=20
    )
    assert title == "Short"
    assert len(capped_detail) == 20
    assert capped_detail.endswith("…")


def test_merge_migrated_detail_line_deduplication_and_substring_safety() -> None:
    assert merge_migrated_detail("- A", None) == "- A"
    assert merge_migrated_detail(None, "- B") == "- B"
    assert merge_migrated_detail("- A\n- B", "- B") == "- A\n- B"
    assert merge_migrated_detail("- A", "- A\n- B") == "- A\n- B"
    assert merge_migrated_detail("- A", "- B") == "- A\n- B"

    # Substring containment that is NOT a full line match must NEVER drop prior lines
    assert (
        merge_migrated_detail("- Ask Bob", "- Ask Bob's manager")
        == "- Ask Bob\n- Ask Bob's manager"
    )
    assert merge_migrated_detail("- v1", "- Deploy - v10") == "- v1\n- Deploy - v10"

    assert not field_values_differ("due_time", 0, None)
    assert field_values_differ("due_time", 1000, None)
    assert not field_values_differ("detail", "", None)


def test_build_note_task_link_roundtrip() -> None:
    b64 = build_note_task_link(
        file_id=42,
        file_path="/Note/Journal.note",
        page_index=0,
        page_id="P20261026090000abc",
        task_title="Ship feature",
    )
    dto = ScheduleTaskLinkDTO.from_b64(b64)
    assert dto.app_name == "Note"
    assert dto.path == "/Note/Journal.note"
    assert dto.page == 1
    assert dto.file_id == "42"
    assert dto.page_id == "P20261026090000abc"
    assert dto.task_title == "Ship feature"
