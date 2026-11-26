"""Tests for `supernote.server.components.wiki.compiler` (`WikiCompilerWorker`)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any
from unittest.mock import patch

import pytest

from supernote.server.ai.base import AIError
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
    VfsItemDeletedEvent,
    VfsItemPurgedEvent,
)
from supernote.server.exceptions import CursorExpiredError
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
                        "proposal": {"canonical_slug": "entities/alice"},
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

        await event_bus.publish(
            VfsItemPurgedEvent(user_id=1, item_id=99, name="Old.note", is_folder=False)
        )
        await asyncio.sleep(0.02)

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

    before_status = await wiki_service.get_status(1)
    assert before_status.backfill_total_files == 1
    assert before_status.backfill_remaining_files == 1
    assert before_status.backfill_next_files == ["Journal.note"]

    bf = await worker.run_backfill(1, max_files=5)
    assert bf.events_processed == 1
    assert bf.pages_updated == 1
    assert bf.files_processed == ["Journal.note"]
    assert bf.updated_pages == ["projects/atlas"]
    assert bf.remaining_files == 0

    after_status = await wiki_service.get_status(1)
    assert after_status.backfill_total_files == 1
    assert after_status.backfill_remaining_files == 0
    assert after_status.backfill_next_files == []

    lint_issues = await worker.run_semantic_lint(1)
    assert any(i.issue_type == "contradiction" for i in lint_issues)


async def test_same_batch_delete_preserves_is_source_deleted_on_reemit(
    session_manager: DatabaseSessionManager,
) -> None:
    """Re-emitting a deleted source_ref in the same batch must not clear is_source_deleted."""
    event_bus = LocalEventBus()
    coord = SqliteCoordinationService(session_manager)
    event_log = EventLogService(session_manager, coord, event_bus)
    wiki_service = WikiService(session_manager)

    await wiki_service.upsert_page(
        1,
        WikiUpsertInput(
            slug="projects/beta",
            title="Beta",
            body_md="Initial",
            source_refs=[
                WikiSourceRefDTO(
                    source_type="note_page", source_key="55:p1", file_id=55
                )
            ],
            author_kind="compiler",
        ),
    )

    await event_bus.publish(
        VfsItemDeletedEvent(
            user_id=1,
            item_id=55,
            parent_id=0,
            name="Beta.note",
            full_path="/Note/Beta.note",
            is_folder=False,
        )
    )

    fake_llm = FakeTextGenerationModel(
        responses=[
            {
                "page_ops": [
                    {
                        "slug": "projects/beta",
                        "title": "Beta",
                        "body_md": "Updated text",
                        "source_refs": [
                            {
                                "source_type": "note_page",
                                "source_key": "55:p1",
                                "file_id": 55,
                            }
                        ],
                    }
                ]
            }
        ]
    )
    worker = WikiCompilerWorker(
        config=WikiConfig(enabled=True, auto_compile=False),
        session_manager=session_manager,
        wiki_service=wiki_service,
        event_log_service=event_log,
        event_bus=event_bus,
        text_model=fake_llm,
    )

    res = await worker.compile_user_delta(1)
    assert res.pages_updated == 1
    page = await wiki_service.get_page(1, "projects/beta")
    assert page is not None
    assert all(ref.is_source_deleted for ref in page.source_refs)
    issues = await wiki_service.list_lint_issues(1, status="open")
    assert any(i.issue_type == "stale_source" for i in issues)


async def test_debounce_does_not_cancel_inflight_compile(
    session_manager: DatabaseSessionManager,
) -> None:
    """A new event arriving mid-LLM must schedule a follow-up instead of cancelling."""
    event_bus = LocalEventBus()
    coord = SqliteCoordinationService(session_manager)
    event_log = EventLogService(session_manager, coord, event_bus)
    wiki_service = WikiService(session_manager)

    in_llm = asyncio.Event()
    release_llm = asyncio.Event()
    calls = 0

    class BlockingModel(FakeTextGenerationModel):
        async def generate_json(
            self,
            prompt: str,
            *,
            response_schema: Mapping[str, Any],
            schema_name: str = "response",
            stage: Any = None,
        ) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            if calls == 1:
                in_llm.set()
                await release_llm.wait()
            return {
                "page_ops": [
                    {
                        "slug": f"projects/run-{calls}",
                        "title": f"Run {calls}",
                        "body_md": "Body",
                    }
                ]
            }

    worker = WikiCompilerWorker(
        config=WikiConfig(enabled=True, auto_compile=True, debounce_seconds=0),
        session_manager=session_manager,
        wiki_service=wiki_service,
        event_log_service=event_log,
        event_bus=event_bus,
        text_model=BlockingModel(),
    )
    await worker.start()
    try:
        await event_bus.publish(
            NotePageTranscribedEvent(
                user_id=1, file_id=1, file_path="/A.note", page_id="p1", page_index=0
            )
        )
        await asyncio.wait_for(in_llm.wait(), timeout=2.0)

        # Second event arrives while compile #1 is blocked in the LLM call.
        await event_bus.publish(
            NotePageTranscribedEvent(
                user_id=1, file_id=1, file_path="/A.note", page_id="p2", page_index=1
            )
        )
        await asyncio.sleep(0.02)
        release_llm.set()

        for _ in range(50):
            if await wiki_service.get_page(1, "projects/run-2") is not None:
                break
            await asyncio.sleep(0.02)

        assert await wiki_service.get_page(1, "projects/run-1") is not None
        assert await wiki_service.get_page(1, "projects/run-2") is not None
    finally:
        await worker.stop()


async def test_cursor_expired_and_ai_error_update_checkpoint(
    session_manager: DatabaseSessionManager,
) -> None:
    event_bus = LocalEventBus()
    coord = SqliteCoordinationService(session_manager)
    event_log = EventLogService(session_manager, coord, event_bus)
    wiki_service = WikiService(session_manager)

    class FailingModel(FakeTextGenerationModel):
        async def generate_json(
            self,
            prompt: str,
            *,
            response_schema: Mapping[str, Any],
            schema_name: str = "response",
            stage: Any = None,
        ) -> dict[str, Any]:
            raise AIError("upstream 503")

    worker = WikiCompilerWorker(
        config=WikiConfig(enabled=True, auto_compile=False),
        session_manager=session_manager,
        wiki_service=wiki_service,
        event_log_service=event_log,
        event_bus=event_bus,
        text_model=FailingModel(),
    )

    with patch.object(
        event_log, "list_events", side_effect=CursorExpiredError("expired")
    ):
        paused = await worker.compile_user_delta(1)
    assert paused.status == "paused"
    assert (await wiki_service.get_status(1)).status == "paused"

    await event_bus.publish(
        NotePageTranscribedEvent(
            user_id=1, file_id=9, file_path="/Err.note", page_id="p1", page_index=0
        )
    )
    with pytest.raises(AIError, match="upstream 503"):
        await worker.compile_user_delta(1)
    status = await wiki_service.get_status(1)
    assert status.status == "error"
    assert status.last_error == "upstream 503"


async def test_apply_compile_plan_strips_redundant_source_type_prefix(
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
            file_name="Spec.note",
            is_folder="N",
            is_active="Y",
        )
        session.add(note)
        await session.flush()
        session.add(
            NotePageContentDO(
                file_id=note.id,
                page_index=0,
                page_id="P1",
                text_content="Aurora spec",
            )
        )
        await session.commit()

    fake_llm = FakeTextGenerationModel(
        responses=[
            {
                "page_ops": [
                    {
                        "slug": "projects/aurora",
                        "title": "Aurora",
                        "page_kind": "project",
                        "body_md": "Spec body",
                        "source_refs": [
                            {
                                "source_type": "note_page",
                                "source_key": "note_page:1:P1",
                                "file_id": 1,
                            }
                        ],
                    }
                ]
            }
        ]
    )
    worker = WikiCompilerWorker(
        config=WikiConfig(enabled=True, auto_compile=False),
        session_manager=session_manager,
        wiki_service=wiki_service,
        event_log_service=event_log,
        event_bus=event_bus,
        text_model=fake_llm,
    )
    res = await worker.run_backfill(1, max_files=5)
    assert res.pages_updated == 1
    page = await wiki_service.get_page(1, "projects/aurora")
    assert page is not None
    assert [r.source_key for r in page.source_refs] == ["1:P1"]


async def test_apply_compile_plan_skips_llm_index_op_without_consuming_page_cap(
    session_manager: DatabaseSessionManager,
) -> None:
    event_bus = LocalEventBus()
    coord = SqliteCoordinationService(session_manager)
    event_log = EventLogService(session_manager, coord, event_bus)
    wiki_service = WikiService(session_manager)

    fake_llm = FakeTextGenerationModel(
        responses=[
            {
                "page_ops": [
                    {
                        "slug": "index",
                        "title": "LLM Index",
                        "page_kind": "index",
                        "body_md": "Should be ignored",
                    },
                    {
                        "slug": "projects/one",
                        "title": "One",
                        "page_kind": "project",
                        "body_md": "First",
                    },
                    {
                        "slug": "projects/two",
                        "title": "Two",
                        "page_kind": "project",
                        "body_md": "Second",
                    },
                ]
            }
        ]
    )
    worker = WikiCompilerWorker(
        config=WikiConfig(enabled=True, auto_compile=False, max_pages_per_batch=2),
        session_manager=session_manager,
        wiki_service=wiki_service,
        event_log_service=event_log,
        event_bus=event_bus,
        text_model=fake_llm,
    )
    await event_bus.publish(
        NotePageTranscribedEvent(
            user_id=1,
            file_id=10,
            file_path="/Note/Test.note",
            page_id="p1",
            page_index=0,
            text_content="One and Two",
        )
    )
    res = await worker.compile_user_delta(1)
    # Both real pages were applied despite the leading LLM `index` op.
    assert res.pages_updated == 2
    assert await wiki_service.get_page(1, "projects/one") is not None
    assert await wiki_service.get_page(1, "projects/two") is not None
    # Deterministic `index` was written once (version 1) by `sync_index_page`.
    index_page = await wiki_service.get_page(1, "index")
    assert index_page is not None
    assert index_page.version == 1
    assert "[[projects/one]]" in index_page.body_md
    assert "[[projects/two]]" in index_page.body_md


async def test_background_backfill_runs_all_notebooks_stops_cleanly_and_resets(
    session_manager: DatabaseSessionManager,
) -> None:
    event_bus = LocalEventBus()
    coord = SqliteCoordinationService(session_manager)
    event_log = EventLogService(session_manager, coord, event_bus)
    wiki_service = WikiService(session_manager)

    async with session_manager.session() as session:
        for fid in (10, 20, 30):
            session.add(
                UserFileDO(
                    id=fid,
                    user_id=1,
                    directory_id=0,
                    file_name=f"Notebook_{fid}.note",
                    is_folder="N",
                    is_active="Y",
                )
            )
            session.add(
                NotePageContentDO(
                    file_id=fid,
                    page_index=0,
                    page_id=f"P{fid}",
                    text_content=f"Content for {fid}",
                )
            )
        await session.commit()

    in_first_turn = asyncio.Event()
    release_first_turn = asyncio.Event()
    calls = 0

    class ControlledModel(FakeTextGenerationModel):
        async def generate_json(
            self,
            prompt: str,
            *,
            response_schema: Mapping[str, Any],
            schema_name: str = "response",
            stage: Any = None,
        ) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            if calls == 1:
                in_first_turn.set()
                await release_first_turn.wait()
            return {
                "page_ops": [
                    {
                        "slug": f"topics/note-{calls}",
                        "title": f"Note {calls}",
                        "page_kind": "topic",
                        "body_md": f"Compiled turn {calls}",
                    }
                ]
            }

    worker = WikiCompilerWorker(
        config=WikiConfig(enabled=True, auto_compile=False),
        session_manager=session_manager,
        wiki_service=wiki_service,
        event_log_service=event_log,
        event_bus=event_bus,
        text_model=ControlledModel(),
    )
    try:
        started = await worker.start_backfill_job(1, max_files_per_turn=1)
        assert started.status == "backfilling"
        assert started.remaining_files == 3

        await asyncio.wait_for(in_first_turn.wait(), timeout=2.0)

        # Reset must fail while a background backfill is active.
        with pytest.raises(ValueError, match="Stop the running backfill"):
            await worker.reset_backfill(1)

        # Request graceful stop; turn 1 finishes and turns 2 & 3 do not run.
        stopped = await worker.stop_backfill_job(1)
        assert stopped.status == "stopping"
        release_first_turn.set()

        for _ in range(50):
            if not worker.is_backfill_running(1):
                break
            await asyncio.sleep(0.02)

        assert not worker.is_backfill_running(1)
        assert calls == 1
        mid_status = await wiki_service.get_status(1)
        assert mid_status.status == "idle"
        assert mid_status.backfill_remaining_files == 2

        # Resume background backfill to finish remaining 2 notebooks automatically.
        resumed = await worker.start_backfill_job(1, max_files_per_turn=1)
        assert resumed.status == "backfilling"
        for _ in range(50):
            if not worker.is_backfill_running(1):
                break
            await asyncio.sleep(0.02)

        assert not worker.is_backfill_running(1)
        assert calls == 3
        done_status = await wiki_service.get_status(1)
        assert done_status.status == "idle"
        assert done_status.backfill_remaining_files == 0

        # Reset cursor queues all 3 notebooks again.
        reset_res = await worker.reset_backfill(1)
        assert reset_res.status == "idle"
        assert reset_res.remaining_files == 3
        after_reset = await wiki_service.get_status(1)
        assert after_reset.backfill_remaining_files == 3
    finally:
        await worker.stop()
