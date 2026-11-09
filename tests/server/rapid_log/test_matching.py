"""Unit and scenario tests for `supernote.server.rapid_log.matching`."""

from __future__ import annotations

from supernote.server.rapid_log.matching import in_page_fuzzy_similarity
from tests.server.rapid_log.conftest import MagicTodoSimulator, make_page_id


def test_in_page_fuzzy_similarity_unit_rules() -> None:
    assert in_page_fuzzy_similarity("", "call bob") == 0.0
    assert in_page_fuzzy_similarity("call bob", "call bob") == 1.0
    # Word-boundary prefix extension
    assert in_page_fuzzy_similarity("call bob", "call bob at 5pm") > 0.85
    # OCR digit-letter jitter inside word (`b0b` -> `bob`) matches
    assert (
        in_page_fuzzy_similarity("call b0b about roadmap", "call bob about roadmap")
        >= 0.82
    )
    # Distinct numbered items must NEVER fuzzy-match
    assert in_page_fuzzy_similarity("complete phase 1", "complete phase 2") == 0.0
    assert (
        in_page_fuzzy_similarity("q1 architecture review", "q2 architecture review")
        == 0.0
    )
    # Short distinct words do not match
    assert in_page_fuzzy_similarity("buy milk", "buy eggs") == 0.0


def test_in_page_fuzzy_matching_handles_ocr_jitter_and_appended_words_safely(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(1, "/Note/Daily.note")
    p1 = make_page_id(2026, 10, 26, 9, 0)

    simulator.set_page(
        1,
        p1,
        "• Call B0b about roadmap\n• Send invoice\n• Complete Phase 1",
    )
    simulator.sync_notebook(1)
    simulator.advance(minutes=5)
    simulator.digital_edit("task-1", task_list_id="group-eng")
    simulator.digital_edit("task-2", task_list_id="group-finance")

    # OCR fixes `B0b` -> `Bob`, user appends `by 5pm`, and replaces Phase 1 with Phase 2
    simulator.advance(minutes=10)
    simulator.set_page(
        1,
        p1,
        "• Call Bob about roadmap\n• Send invoice by 5pm\n• Complete Phase 2",
    )
    plan = simulator.sync_notebook(1)

    assert [c.title for c in plan.create_tasks] == ["Complete Phase 2"]
    assert [d.task_id for d in plan.delete_tasks] == ["task-3"]
    assert simulator.tasks["task-1"].title == "Call Bob about roadmap"
    assert simulator.tasks["task-1"].task_list_id == "group-eng"
    assert simulator.tasks["task-2"].title == "Send invoice by 5pm"
    assert simulator.tasks["task-2"].task_list_id == "group-finance"


def test_duplicate_identical_bullets_on_same_page_and_top_duplicate_erasure(
    simulator: MagicTodoSimulator,
) -> None:
    simulator.create_notebook(1, "/Note/Projects.note")
    p1 = make_page_id(2026, 10, 26, 9, 0)

    simulator.set_page(
        1,
        p1,
        """# Morning
• Drink water

# Evening
• Drink water
""",
    )
    plan1 = simulator.sync_notebook(1)
    assert len(plan1.create_tasks) == 2
    assert set(simulator.tasks) == {"task-1", "task-2"}

    # Complete the FIRST occurrence in ink -> task-1 completes, task-2 stays open
    simulator.advance(minutes=20)
    simulator.set_page(
        1,
        p1,
        """# Morning
X Drink water

# Evening
• Drink water
""",
    )
    simulator.sync_notebook(1)
    assert simulator.tasks["task-1"].status == "completed"
    assert simulator.tasks["task-2"].status == "needsAction"

    # Erase the completed top duplicate -> task-2 stays open and task-1 stays completed!
    simulator.advance(minutes=20)
    simulator.set_page(
        1,
        p1,
        """# Evening
• Drink water
""",
    )
    plan_erase_top = simulator.sync_notebook(1)
    assert not plan_erase_top.has_task_mutations
    assert simulator.tasks["task-1"].status == "completed"
    assert simulator.tasks["task-2"].status == "needsAction"
