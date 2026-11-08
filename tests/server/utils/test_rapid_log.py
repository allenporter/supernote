"""Unit tests for the Bullet Journal Rapid Logging parser."""

from supernote.server.utils.rapid_log import (
    RapidLogKind,
    RapidLogTaskState,
    parse_rapid_log,
)


def test_parse_rapid_log_tasks_events_notes_and_signifiers() -> None:
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
* - Importantstarred note
o 10:00 AM Team standup event
* o 2:00 PM Executive review
Plain paragraph text
---
"""
    items = parse_rapid_log(transcript)

    assert len(items) == 16

    tasks = [i for i in items if i.kind == RapidLogKind.TASK]
    events = [i for i in items if i.kind == RapidLogKind.EVENT]
    notes = [i for i in items if i.kind == RapidLogKind.NOTE]

    assert len(tasks) == 12
    assert len(events) == 2
    assert len(notes) == 2

    by_text = {t.text: t for t in items}

    assert by_text["Incomplete bullet task"].task_state == RapidLogTaskState.INCOMPLETE
    assert not by_text["Incomplete bullet task"].is_starred

    assert by_text["Starred critical task"].task_state == RapidLogTaskState.INCOMPLETE
    assert by_text["Starred critical task"].is_starred

    assert by_text["Completed task"].task_state == RapidLogTaskState.COMPLETED
    assert by_text["Starred completed task"].is_starred

    assert (
        by_text["Migrated forward task"].task_state
        == RapidLogTaskState.MIGRATED_FORWARD
    )
    assert by_text["Starred migrated forward"].is_starred
    assert (
        by_text["Migrated scheduled task"].task_state
        == RapidLogTaskState.MIGRATED_SCHEDULED
    )

    assert by_text["Markdown checkbox open"].task_state == RapidLogTaskState.INCOMPLETE
    assert by_text["Starred markdown checkbox"].is_starred
    assert by_text["Bare checkbox open"].task_state == RapidLogTaskState.INCOMPLETE
    assert by_text["Markdown checkbox done"].task_state == RapidLogTaskState.COMPLETED
    assert (
        by_text["Bare checkbox done uppercase"].task_state
        == RapidLogTaskState.COMPLETED
    )

    assert by_text["Just a regular note"].kind == RapidLogKind.NOTE
    assert by_text["Just a regular note"].task_state is None
    assert by_text["Importantstarred note"].kind == RapidLogKind.NOTE
    assert by_text["Importantstarred note"].is_starred

    assert by_text["10:00 AM Team standup event"].kind == RapidLogKind.EVENT
    assert by_text["10:00 AM Team standup event"].task_state is None
    assert by_text["2:00 PM Executive review"].kind == RapidLogKind.EVENT
    assert by_text["2:00 PM Executive review"].is_starred


def test_parse_strikethrough_cancellations_across_entry_kinds() -> None:
    transcript = """~~• Call Bob~~
~~* • Fix prod alert~~
• ~~Update roadmap~~
~~Plain crossed out task~~
~~- Crossed out note~~
~~o Crossed out 4pm event~~
o ~~Rescheduled dentist~~
"""
    items = parse_rapid_log(transcript)
    assert len(items) == 7

    assert items[0].kind == RapidLogKind.TASK
    assert items[0].text == "Call Bob"
    assert items[0].task_state == RapidLogTaskState.CANCELLED
    assert items[0].is_cancelled

    assert items[1].kind == RapidLogKind.TASK
    assert items[1].text == "Fix prod alert"
    assert items[1].is_starred
    assert items[1].is_cancelled

    assert items[2].kind == RapidLogKind.TASK
    assert items[2].text == "Update roadmap"
    assert items[2].task_state == RapidLogTaskState.CANCELLED

    assert items[3].kind == RapidLogKind.TASK
    assert items[3].text == "Plain crossed out task"
    assert items[3].task_state == RapidLogTaskState.CANCELLED

    assert items[4].kind == RapidLogKind.NOTE
    assert items[4].text == "Crossed out note"
    assert items[4].is_cancelled
    assert items[4].task_state is None

    assert items[5].kind == RapidLogKind.EVENT
    assert items[5].text == "Crossed out 4pm event"
    assert items[5].is_cancelled

    assert items[6].kind == RapidLogKind.EVENT
    assert items[6].text == "Rescheduled dentist"
    assert items[6].is_cancelled


def test_parse_nested_hierarchy_and_details() -> None:
    transcript = """* • Send Q3 architecture proposal
  - Include SQLite benchmark numbers
  - CC Alice
    - Also check with Bob
o 2:00 PM Architecture review
  - Room 4B
  Dial-in link in invite
• Follow up with design
\t- Ask about dark mode icons
Plain heading
  Indented under plain heading should not attach
"""
    items = parse_rapid_log(transcript)
    assert len(items) == 3

    proposal = items[0]
    assert proposal.kind == RapidLogKind.TASK
    assert proposal.text == "Send Q3 architecture proposal"
    assert proposal.detail == (
        "- Include SQLite benchmark numbers\n- CC Alice\n  - Also check with Bob"
    )
    assert len(proposal.children) == 2
    assert proposal.children[0].kind == RapidLogKind.NOTE
    assert proposal.children[0].text == "Include SQLite benchmark numbers"
    assert proposal.children[1].text == "CC Alice"
    assert proposal.children[1].detail == "- Also check with Bob"
    assert len(proposal.children[1].children) == 1
    assert proposal.children[1].children[0].text == "Also check with Bob"

    event = items[1]
    assert event.kind == RapidLogKind.EVENT
    assert event.text == "2:00 PM Architecture review"
    assert event.detail == "- Room 4B\nDial-in link in invite"
    assert len(event.children) == 2
    assert event.children[0].text == "Room 4B"
    assert event.children[1].kind == RapidLogKind.NOTE
    assert event.children[1].text == "Dial-in link in invite"

    followup = items[2]
    assert followup.kind == RapidLogKind.TASK
    assert followup.detail == "- Ask about dark mode icons"
