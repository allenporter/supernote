"""Unit tests for the Bullet Journal rapid-logging and checkbox task parser."""

from supernote.server.utils.task_parser import (
    ExtractedTaskState,
    normalize_task_title,
    parse_page_tasks,
)


def test_normalize_task_title() -> None:
    assert normalize_task_title("  Send   Q3  Proposal. ") == "send q3 proposal"
    assert normalize_task_title("Call Bob;") == "call bob"
    assert normalize_task_title("Review PR #452") == "review pr #452"


def test_parse_rapid_logging_states_and_signifiers() -> None:
    transcript = """# 2026-10-26
• Incomplete bullet task
* • Starred critical task
X Completed task
* X Starred completed task
> Migrated forward task
* > Starred migrated forward
< Migrated scheduled task
- [ ] Markdown checkbox open
* - [ ] Starred markdown checkbox
[ ] Bare checkbox open
- [x] Markdown checkbox done
[X] Bare checkbox done uppercase
- Just a regular note
o 10:00 AM Team standup event
Plain paragraph text
"""
    tasks = parse_page_tasks(transcript)

    assert len(tasks) == 12

    by_title = {t.raw_title: t for t in tasks}

    t1 = by_title["Incomplete bullet task"]
    assert t1.state == ExtractedTaskState.INCOMPLETE
    assert not t1.is_starred

    t2 = by_title["Starred critical task"]
    assert t2.state == ExtractedTaskState.INCOMPLETE
    assert t2.is_starred

    t3 = by_title["Completed task"]
    assert t3.state == ExtractedTaskState.COMPLETED
    assert not t3.is_starred

    t4 = by_title["Starred completed task"]
    assert t4.state == ExtractedTaskState.COMPLETED
    assert t4.is_starred

    t5 = by_title["Migrated forward task"]
    assert t5.state == ExtractedTaskState.MIGRATED_FORWARD
    assert not t5.is_starred

    t6 = by_title["Starred migrated forward"]
    assert t6.state == ExtractedTaskState.MIGRATED_FORWARD
    assert t6.is_starred

    t7 = by_title["Migrated scheduled task"]
    assert t7.state == ExtractedTaskState.MIGRATED_SCHEDULED

    t8 = by_title["Markdown checkbox open"]
    assert t8.state == ExtractedTaskState.INCOMPLETE

    t9 = by_title["Starred markdown checkbox"]
    assert t9.state == ExtractedTaskState.INCOMPLETE
    assert t9.is_starred

    t10 = by_title["Bare checkbox open"]
    assert t10.state == ExtractedTaskState.INCOMPLETE

    t11 = by_title["Markdown checkbox done"]
    assert t11.state == ExtractedTaskState.COMPLETED

    t12 = by_title["Bare checkbox done uppercase"]
    assert t12.state == ExtractedTaskState.COMPLETED


def test_parse_strikethrough_cancelled_tasks() -> None:
    transcript = """~~• Call Bob~~
~~* • Fix prod alert~~
• ~~Update roadmap~~
~~Plain crossed out task~~
~~- Crossed out note should be ignored~~
~~o Crossed out event should be ignored~~
"""
    tasks = parse_page_tasks(transcript)
    assert len(tasks) == 4

    assert tasks[0].raw_title == "Call Bob"
    assert tasks[0].normalized_title == "call bob"
    assert tasks[0].state == ExtractedTaskState.CANCELLED
    assert not tasks[0].is_starred

    assert tasks[1].raw_title == "Fix prod alert"
    assert tasks[1].state == ExtractedTaskState.CANCELLED
    assert tasks[1].is_starred

    assert tasks[2].raw_title == "Update roadmap"
    assert tasks[2].state == ExtractedTaskState.CANCELLED

    assert tasks[3].raw_title == "Plain crossed out task"
    assert tasks[3].state == ExtractedTaskState.CANCELLED


def test_parse_indented_context_notes() -> None:
    transcript = """* • Send Q3 architecture proposal
  - Include SQLite benchmark numbers
  - CC Alice
    - Also check with Bob
o 2:00 PM Architecture review
  - Room 4B (should not attach to task!)
• Follow up with design
\t- Ask about dark mode icons
"""
    tasks = parse_page_tasks(transcript)
    assert len(tasks) == 2

    first = tasks[0]
    assert first.raw_title == "Send Q3 architecture proposal"
    assert first.is_starred
    assert first.detail == (
        "- Include SQLite benchmark numbers\n- CC Alice\n  - Also check with Bob"
    )

    second = tasks[1]
    assert second.raw_title == "Follow up with design"
    assert second.detail == "- Ask about dark mode icons"


def test_same_page_deduplication_merges_latest_state_and_details() -> None:
    transcript = """• Call Bob
  - Ask about timeline
X Call Bob.
  - Confirmed for Friday
"""
    tasks = parse_page_tasks(transcript)
    assert len(tasks) == 1
    assert tasks[0].normalized_title == "call bob"
    assert tasks[0].state == ExtractedTaskState.COMPLETED
    assert tasks[0].detail == "- Ask about timeline\n- Confirmed for Friday"
