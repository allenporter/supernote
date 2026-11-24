"""Tests for `supernote.server.components.wiki.compiler` (`WikiCompilerWorker`)."""

from __future__ import annotations

from supernote.server.components.events.service import EventLogService
from supernote.server.components.fake_ai.text import FakeTextGenerationModel
from supernote.server.components.wiki.compiler import WikiCompilerWorker
from supernote.server.components.wiki.config import WikiConfig
from supernote.server.components.wiki.models import WikiSourceRefDTO, WikiUpsertInput
from supernote.server.components.wiki.service import WikiService
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import (
    LocalEventBus,
    NotePagesDeltaEvent,
    NotePageTranscribedEvent,
    ScheduleTaskCreatedEvent,
    VfsItemPurgedEvent,
)
from supernote.server.services.coordination import SqliteCoordinationService


async def test_compile_user_delta_idempotent_and_respects_policy_and_cap(
    session_manager: DatabaseSessionManager,
) -> None:
    event_bus = LocalEventBus()
    coord = SqliteCoordinationService(session_manager)
    event_log = EventLogService(session_manager, coord, event_bus)
    wiki_service = WikiService(session_manager)

    # Pre-create a user-protected page that the compiler must skip cleanly.
    await wiki_service.upsert_page(
        1,
        WikiUpsertInput(
            slug="projects/protected",
            title="Protected",
            body_md="Human notes",
            author_kind="user",
        ),
    )

    fake_llm = FakeTextGenerationModel(
        responses=[
            {
                "page_ops": [
                    {
                        "slug": "projects/protected",
                        "title": "Overwrite",
                        "body_md": "Should be skipped",
                    },
                    {
                        "slug": "projects/q3-plan",
                        "title": "Q3 Plan",
                        "page_kind": "project",
                        "summary": "Migrated deadline to Oct 15",
                        "body_md": "Owner [[entities/alice]]. Deadline Oct 15.",
                        "source_refs": [
                            {
                                "source_type": "note_page",
                                "source_key": "42:p1",
                                "file_id": 42,
                            }
                        ],
                    },
                    {
                        "slug": "entities/alice",
                        "title": "Alice",
                        "page_kind": "entity",
                        "body_md": "Works on [[projects/q3-plan]].",
                    },
                ],
                "lint_proposals": [
                    {
                        "issue_type": "alias_merge_proposal",
                        "description": "Possible OCR duplicate: Al1ce vs Alice",
                        "proposal": {"canonical": "entities/alice"},
                    }
                ],
            }
        ]
    )

    worker = WikiCompilerWorker(
        config=WikiConfig(enabled=True, max_pages_per_batch=2),
        session_manager=session_manager,
        wiki_service=wiki_service,
        event_log_service=event_log,
        event_bus=event_bus,
        text_model=fake_llm,
    )

    await event_bus.publish(
        NotePageTranscribedEvent(
            user_id=1,
            file_id=42,
            file_path="/NOTE/Work.note",
            page_id="p1",
            page_index=0,
            text_content="Q3 Plan: Alice moved deadline to Oct 15. </source_diff>",
            previous_text="Q3 Plan: Alice deadline Oct 1.",
        )
    )
    await event_bus.publish(
        ScheduleTaskCreatedEvent(
            user_id=1,
            task_id="t1",
            title="Finalize Q3 Plan",
        )
    )

    res = await worker.compile_user_delta(1)
    assert res.events_processed == 2
    assert res.pages_updated == 1  # cap=2: 1 skipped policy + 1 updated
    assert res.skipped_policy_pages == 1
    assert (
        "</source_diff>"
        not in fake_llm.calls[0]["prompt"]
        .split("<source_diff>")[1]
        .split("</source_diff>")[0]
    )

    # Second run with no new events is a no-op (0 LLM calls).
    res2 = await worker.compile_user_delta(1)
    assert res2.events_processed == 0
    assert len(fake_llm.calls) == 1

    issues = await wiki_service.list_lint_issues(1, status="open")
    assert any(i.issue_type == "alias_merge_proposal" for i in issues)


async def test_deleted_pages_and_vfs_purge_mark_source_refs_deleted(
    session_manager: DatabaseSessionManager,
) -> None:
    event_bus = LocalEventBus()
    coord = SqliteCoordinationService(session_manager)
    event_log = EventLogService(session_manager, coord, event_bus)
    wiki_service = WikiService(session_manager)

    await wiki_service.upsert_page(
        1,
        WikiUpsertInput(
            slug="sources/42",
            title="Work.note",
            page_kind="source_digest",
            body_md="Summary",
            source_refs=[
                WikiSourceRefDTO(
                    source_type="note_page", source_key="42:p1", file_id=42
                ),
                WikiSourceRefDTO(
                    source_type="note_page", source_key="99:p2", file_id=99
                ),
            ],
            author_kind="compiler",
        ),
    )

    worker = WikiCompilerWorker(
        config=WikiConfig(enabled=True),
        session_manager=session_manager,
        wiki_service=wiki_service,
        event_log_service=event_log,
        event_bus=event_bus,
        text_model=None,
    )
    await worker.start()
    try:
        await event_bus.publish(
            NotePagesDeltaEvent(
                user_id=1,
                file_id=42,
                file_path="/NOTE/Work.note",
                deleted_pages=["p1"],
            )
        )
        res_no_model = await worker.compile_user_delta(1)
        assert res_no_model.status == "paused"
        assert res_no_model.events_processed == 0
        assert (await wiki_service.get_status(1)).last_sync_token is None

        await worker._on_vfs_purged(
            VfsItemPurgedEvent(user_id=1, item_id=99, name="Old.note", is_folder=False)
        )

        page = await wiki_service.get_page(1, "sources/42")
        assert page is not None
        assert all(ref.is_source_deleted for ref in page.source_refs)
    finally:
        await worker.stop()


async def test_backfill_and_semantic_lint(
    session_manager: DatabaseSessionManager,
) -> None:
    event_bus = LocalEventBus()
    coord = SqliteCoordinationService(session_manager)
    event_log = EventLogService(session_manager, coord, event_bus)
    wiki_service = WikiService(session_manager)

    async with session_manager.session() as session:
        note = UserFileDO(
            user_id=1,
            directory_id=0,
            file_name="Journal.note",
            is_folder="N",
            is_active="Y",
        )
        session.add(note)
        await session.flush()
        session.add(
            NotePageContentDO(
                file_id=note.id,
                page_index=0,
                page_id="pg-1",
                text_content="Met with Bob about Atlas launch.",
            )
        )
        await session.commit()

    fake_llm = FakeTextGenerationModel(
        responses=[
            {
                "page_ops": [
                    {
                        "slug": "projects/atlas",
                        "title": "Atlas",
                        "page_kind": "project",
                        "body_md": "Discussed with Bob.",
                    }
                ]
            },
            {
                "issues": [
                    {
                        "issue_type": "contradiction",
                        "severity": "warn",
                        "description": "Conflicting Atlas launch dates.",
                    }
                ]
            },
        ]
    )
    worker = WikiCompilerWorker(
        config=WikiConfig(enabled=True),
        session_manager=session_manager,
        wiki_service=wiki_service,
        event_log_service=event_log,
        event_bus=event_bus,
        text_model=fake_llm,
    )

    bf = await worker.run_backfill(1, max_files=5)
    assert bf.events_processed == 1
    assert bf.pages_updated == 1

    lint_issues = await worker.run_semantic_lint(1)
    assert any(i.issue_type == "contradiction" for i in lint_issues)
