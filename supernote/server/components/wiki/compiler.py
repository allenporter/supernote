"""Event-driven incremental LLM Wiki compiler, backfill, and semantic lint worker.

Keeps each user's compiled wiki fresh and invalidates stale provenance as source
notebooks and schedule tasks change, without re-scanning the entire vault:

- **Freshness & incremental updates (`DomainEventRecorded` + `EventLogService`)**:
  `DomainEventRecorded` is used only as a lightweight, per-user debounced wake-up
  signal (coalescing multi-page sync bursts). On wake-up, the worker drains the
  durable `f_user_event` log from `f_wiki_checkpoint.last_sync_token` so nothing
  is missed across restarts:
  - Content/metadata events (`note.page_transcribed`, `note.pages_delta`,
    `schedule.task_created`, `schedule.task_updated`, `file.moved`) drive
    incremental LLM synthesis to keep affected wiki pages current.
  - Soft-delete / invalidation events (`file.deleted` when a file moves to the
    recycle bin, deleted pages in `note.pages_delta`, `schedule.task_deleted`)
    mark matching `f_wiki_source_ref.is_source_deleted = True` so structural
    lint flags `stale_source` instead of leaving silent dead citations.
- **Hard-purge invalidation backstop (`VfsItemPurgedEvent`)**:
  In normal `auto_compile=True` operation, `file.deleted` (recycle bin) already
  marks `is_source_deleted = True`. Subscribing to `VfsItemPurgedEvent` is an
  idempotent backstop for cases where `file.deleted` was not processed by this
  worker (for example, `auto_compile=False` external-agent mode, or a file
  purged after an expired cursor / pre-wiki deletion) once the underlying
  `UserFileDO` and `NotePageContentDO` rows are permanently removed.

Execution invariants: LLM calls run strictly outside open SQLite sessions,
writes enforce `max_pages_per_batch` and `edit_policy`, zero-LLM structural
lint (`broken_link`, `orphan_page`, `stale_source`) runs after every compile,
and LLM semantic findings (`contradiction`, `alias_merge_proposal`) are recorded
in `f_wiki_lint_issue` for explicit human/agent triage.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from aiohttp import web
from sqlalchemy import select

from supernote.models.events import DomainEventType
from supernote.server.ai.base import AIError
from supernote.server.ai.models.text import TextGenerationModel
from supernote.server.components.events.service import EventLogService
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.schedule import ScheduleTaskDO
from supernote.server.db.models.wiki import WikiCheckpointDO, WikiLintIssueDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import (
    DomainEventRecorded,
    LocalEventBus,
    VfsItemPurgedEvent,
)
from supernote.server.exceptions import CursorExpiredError
from supernote.server.metrics import AIStage

from .config import WikiConfig
from .models import (
    VALID_PAGE_KINDS,
    WikiLintIssueDTO,
    WikiPolicyError,
    WikiSourceRefDTO,
    WikiUpsertInput,
)
from .prompts import (
    WIKI_COMPILE_SCHEMA,
    WIKI_LINT_SCHEMA,
    build_compile_prompt,
    build_lint_prompt,
)
from .service import WikiService, _make_dedup_key
from .sources import (
    load_linked_context,
    mark_deleted_sources_from_events,
    mark_file_sources_deleted,
)

__all__ = [
    "WIKI_COMPILER_KEY",
    "WIKI_RELEVANT_EVENT_TYPES",
    "WikiCompileResult",
    "WikiCompilerWorker",
]

logger = logging.getLogger(__name__)

WIKI_RELEVANT_EVENT_TYPES: tuple[str, ...] = (
    DomainEventType.NOTE_PAGE_TRANSCRIBED.value,
    DomainEventType.NOTE_PAGES_DELTA.value,
    DomainEventType.SCHEDULE_TASK_CREATED.value,
    DomainEventType.SCHEDULE_TASK_UPDATED.value,
    DomainEventType.SCHEDULE_TASK_DELETED.value,
    DomainEventType.FILE_MOVED.value,
    DomainEventType.FILE_DELETED.value,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class WikiCompileResult:
    """Summary of one incremental compile or backfill pass."""

    events_processed: int
    pages_updated: int
    skipped_policy_pages: int
    lint_issues_open: int
    status: str


class WikiCompilerWorker:
    """Per-user serialized incremental compiler driven by `EventLogService`."""

    def __init__(
        self,
        *,
        config: WikiConfig,
        session_manager: DatabaseSessionManager,
        wiki_service: WikiService,
        event_log_service: EventLogService,
        event_bus: LocalEventBus,
        text_model: TextGenerationModel | None,
    ) -> None:
        self._config = config
        self._session_manager = session_manager
        self._wiki_service = wiki_service
        self._event_log_service = event_log_service
        self._event_bus = event_bus
        self._text_model = text_model
        self._user_locks: dict[int, asyncio.Lock] = {}
        self._debounce_tasks: dict[int, asyncio.Task[None]] = {}
        self._started = False
        self._subscribed = False

    def set_text_model(self, text_model: TextGenerationModel | None) -> None:
        """Bind the resolved `TextGenerationModel` after platform finalization."""
        self._text_model = text_model

    async def start(self) -> None:
        """Subscribe once to `DomainEventRecorded` and `VfsItemPurgedEvent`."""
        if self._started:
            return
        self._started = True
        if not self._subscribed:
            self._subscribed = True
            self._event_bus.subscribe(
                VfsItemPurgedEvent, self._on_vfs_purged, inline=False
            )
            if self._config.auto_compile:
                self._event_bus.subscribe(
                    DomainEventRecorded, self._on_event_recorded, inline=False
                )

    async def stop(self) -> None:
        """Cancel pending debounce timers idempotently."""
        self._started = False
        tasks = list(self._debounce_tasks.values())
        self._debounce_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _on_event_recorded(self, event: DomainEventRecorded) -> None:
        if not self._started or event.event_type not in WIKI_RELEVANT_EVENT_TYPES:
            return
        self._schedule_user_compile(event.user_id)

    async def _on_vfs_purged(self, event: VfsItemPurgedEvent) -> None:
        """Mark wiki source refs citing a permanently purged VFS file as deleted."""
        if not self._started:
            return
        await mark_file_sources_deleted(
            self._session_manager, event.user_id, event.item_id
        )

    def _schedule_user_compile(self, user_id: int) -> None:
        if existing := self._debounce_tasks.get(user_id):
            existing.cancel()

        async def _delayed() -> None:
            try:
                if self._config.debounce_seconds > 0:
                    await asyncio.sleep(self._config.debounce_seconds)
                await self.compile_user_delta(user_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Wiki incremental compile failed for user %s", user_id)
            finally:
                if self._debounce_tasks.get(user_id) is asyncio.current_task():
                    self._debounce_tasks.pop(user_id, None)

        self._debounce_tasks[user_id] = asyncio.create_task(_delayed())

    def _lock_for_user(self, user_id: int) -> asyncio.Lock:
        lock = self._user_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._user_locks[user_id] = lock
        return lock

    async def compile_user_delta(self, user_id: int) -> WikiCompileResult:
        """Drain uncompiled `f_user_event` diffs for `user_id` and compile atomically."""
        async with self._lock_for_user(user_id):
            cp = await self._get_or_create_checkpoint(user_id)
            try:
                page = await self._event_log_service.list_events(
                    user_id=user_id,
                    sync_token=cp.last_sync_token,
                    event_types=list(WIKI_RELEVANT_EVENT_TYPES),
                    limit=50,
                )
            except CursorExpiredError:
                await self._update_checkpoint(
                    user_id,
                    status="paused",
                    last_error="Event cursor expired; run backfill",
                )
                issues = await self._wiki_service.list_lint_issues(
                    user_id, status="open"
                )
                return WikiCompileResult(
                    events_processed=0,
                    pages_updated=0,
                    skipped_policy_pages=0,
                    lint_issues_open=len(issues),
                    status="paused",
                )

            if not page.events:
                if page.next_sync_token != cp.last_sync_token:
                    await self._update_checkpoint(
                        user_id,
                        last_sync_token=page.next_sync_token,
                        status="idle",
                        last_error=None,
                    )
                issues = await self._wiki_service.list_lint_issues(
                    user_id, status="open"
                )
                return WikiCompileResult(
                    events_processed=0,
                    pages_updated=0,
                    skipped_policy_pages=0,
                    lint_issues_open=len(issues),
                    status="idle",
                )

            await mark_deleted_sources_from_events(
                self._session_manager, user_id, page.events
            )
            max_seq = page.events[-1].seq

            if self._text_model is None:
                issues = await self._wiki_service.run_structural_lint(user_id)
                await self._update_checkpoint(
                    user_id,
                    status="paused",
                    last_error="Text generation model not configured",
                )
                return WikiCompileResult(
                    events_processed=0,
                    pages_updated=0,
                    skipped_policy_pages=0,
                    lint_issues_open=len(issues),
                    status="paused",
                )

            linked_context = await load_linked_context(
                self._session_manager, user_id, page.events
            )
            diff_payload = [
                {
                    "seq": ev.seq,
                    "event_type": ev.event_type,
                    "entity_type": ev.entity_type,
                    "entity_id": ev.entity_id,
                    "related_file_id": ev.related_file_id,
                    "payload": ev.payload,
                }
                for ev in page.events
            ]
            all_pages = await self._wiki_service.list_pages(user_id, limit=100)
            prompt = build_compile_prompt(all_pages, diff_payload, linked_context)

            # Execute LLM HTTP call strictly outside any open SQLite session.
            try:
                plan = await self._text_model.generate_json(
                    prompt,
                    response_schema=WIKI_COMPILE_SCHEMA,
                    schema_name="wiki_compile_plan",
                    stage=AIStage.WIKI_COMPILE,
                )
            except AIError as err:
                await self._update_checkpoint(
                    user_id, status="error", last_error=str(err)
                )
                raise

            pages_updated, skipped_policy = await self._apply_compile_plan(
                user_id, plan, source_event_seq=max_seq
            )
            issues = await self._wiki_service.run_structural_lint(user_id)
            await self._update_checkpoint(
                user_id,
                last_sync_token=page.next_sync_token,
                pending_delta=len(page.events),
                status="idle",
                last_error=None,
            )
            return WikiCompileResult(
                events_processed=len(page.events),
                pages_updated=pages_updated,
                skipped_policy_pages=skipped_policy,
                lint_issues_open=len(issues),
                status="idle",
            )

    async def run_backfill(
        self, user_id: int, *, max_files: int = 5
    ) -> WikiCompileResult:
        """Compile existing `.note` OCR transcripts newest-first in bounded chunks."""
        async with self._lock_for_user(user_id):
            if self._text_model is None:
                issues = await self._wiki_service.list_lint_issues(
                    user_id, status="open"
                )
                return WikiCompileResult(
                    events_processed=0,
                    pages_updated=0,
                    skipped_policy_pages=0,
                    lint_issues_open=len(issues),
                    status="idle",
                )

            cp = await self._get_or_create_checkpoint(user_id)
            async with self._session_manager.session() as session:
                stmt = select(UserFileDO).where(
                    UserFileDO.user_id == user_id,
                    UserFileDO.is_active == "Y",
                    UserFileDO.is_folder == "N",
                    UserFileDO.file_name.like("%.note"),
                )
                if cp.backfill_file_cursor is not None:
                    stmt = stmt.where(UserFileDO.id < cp.backfill_file_cursor)
                files = (
                    (
                        await session.execute(
                            stmt.order_by(UserFileDO.id.desc()).limit(
                                max(1, min(max_files, 20))
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if not files:
                    issues = await self._wiki_service.list_lint_issues(
                        user_id, status="open"
                    )
                    return WikiCompileResult(
                        events_processed=0,
                        pages_updated=0,
                        skipped_policy_pages=0,
                        lint_issues_open=len(issues),
                        status="idle",
                    )

                file_ids = [f.id for f in files]
                page_rows = (
                    (
                        await session.execute(
                            select(NotePageContentDO)
                            .join(
                                UserFileDO, UserFileDO.id == NotePageContentDO.file_id
                            )
                            .where(
                                UserFileDO.user_id == user_id,
                                UserFileDO.is_active == "Y",
                                NotePageContentDO.file_id.in_(file_ids),
                                NotePageContentDO.text_content.is_not(None),
                            )
                            .order_by(
                                NotePageContentDO.file_id.desc(),
                                NotePageContentDO.page_index.asc(),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

            file_name_map = {f.id: f.file_name for f in files}
            synthetic_diffs = [
                {
                    "event_type": "backfill.note_page",
                    "entity_id": f"{p.file_id}:{p.page_id}",
                    "related_file_id": p.file_id,
                    "payload": {
                        "file_id": str(p.file_id),
                        "file_path": file_name_map.get(p.file_id, ""),
                        "page_id": p.page_id,
                        "page_index": p.page_index,
                        "text_content": p.text_content or "",
                    },
                }
                for p in page_rows
                if not p.is_blank
            ]

            pages_updated = 0
            skipped_policy = 0
            if synthetic_diffs:
                all_pages = await self._wiki_service.list_pages(user_id, limit=100)
                prompt = build_compile_prompt(
                    all_pages, synthetic_diffs, linked_context={}
                )
                try:
                    plan = await self._text_model.generate_json(
                        prompt,
                        response_schema=WIKI_COMPILE_SCHEMA,
                        schema_name="wiki_compile_plan",
                        stage=AIStage.WIKI_COMPILE,
                    )
                except AIError as err:
                    await self._update_checkpoint(
                        user_id, status="error", last_error=str(err)
                    )
                    raise
                pages_updated, skipped_policy = await self._apply_compile_plan(
                    user_id, plan, source_event_seq=None
                )

            issues = await self._wiki_service.run_structural_lint(user_id)
            await self._update_checkpoint(
                user_id,
                backfill_file_cursor=files[-1].id,
                status="idle",
                last_error=None,
            )
            return WikiCompileResult(
                events_processed=len(synthetic_diffs),
                pages_updated=pages_updated,
                skipped_policy_pages=skipped_policy,
                lint_issues_open=len(issues),
                status="idle",
            )

    async def run_semantic_lint(self, user_id: int) -> list[WikiLintIssueDTO]:
        """Run deterministic structural lint plus optional LLM semantic contradiction/alias audit."""
        async with self._lock_for_user(user_id):
            await self._wiki_service.run_structural_lint(user_id)
            if self._text_model is None:
                return await self._wiki_service.list_lint_issues(user_id, status="open")

            pages = await self._wiki_service.list_pages(user_id, limit=50)
            if not pages:
                return await self._wiki_service.list_lint_issues(user_id, status="open")

            async with self._session_manager.session() as session:
                tasks = (
                    (
                        await session.execute(
                            select(ScheduleTaskDO)
                            .where(ScheduleTaskDO.user_id == user_id)
                            .limit(50)
                        )
                    )
                    .scalars()
                    .all()
                )

            prompt = build_lint_prompt(pages, tasks)
            try:
                report = await self._text_model.generate_json(
                    prompt,
                    response_schema=WIKI_LINT_SCHEMA,
                    schema_name="wiki_lint_report",
                    stage=AIStage.WIKI_LINT,
                )
            except AIError as err:
                await self._update_checkpoint(
                    user_id, status="error", last_error=str(err)
                )
                raise
            await self._record_lint_proposals(user_id, report.get("issues", []))
            await self._update_checkpoint(
                user_id,
                reset_lint=True,
                status="idle",
                last_error=None,
            )
            return await self._wiki_service.list_lint_issues(user_id, status="open")

    async def _apply_compile_plan(
        self,
        user_id: int,
        plan: dict[str, Any],
        *,
        source_event_seq: int | None,
    ) -> tuple[int, int]:
        raw_ops = plan.get("page_ops", [])
        if not isinstance(raw_ops, list):
            return 0, 0

        pages_updated = 0
        skipped_policy = 0
        for op in raw_ops[: self._config.max_pages_per_batch]:
            if not isinstance(op, dict):
                continue
            slug = str(op.get("slug", "")).strip()
            title = str(op.get("title", "")).strip()
            body_md = str(op.get("body_md", ""))
            if not slug or not title:
                continue
            raw_kind = str(op.get("page_kind", "topic"))
            page_kind = raw_kind if raw_kind in VALID_PAGE_KINDS else "topic"
            raw_refs = op.get("source_refs") or []
            source_refs: list[WikiSourceRefDTO] = []
            for r in raw_refs:
                if not (
                    isinstance(r, dict) and r.get("source_type") and r.get("source_key")
                ):
                    continue
                parsed_file_id: int | None = None
                if r.get("file_id") is not None:
                    try:
                        parsed_file_id = int(r["file_id"])
                    except (TypeError, ValueError):
                        parsed_file_id = None
                source_refs.append(
                    WikiSourceRefDTO(
                        source_type=str(r["source_type"]),
                        source_key=str(r["source_key"]),
                        file_id=parsed_file_id,
                        last_event_seq=source_event_seq,
                    )
                )
            try:
                await self._wiki_service.upsert_page(
                    user_id,
                    WikiUpsertInput(
                        slug=slug,
                        title=title,
                        page_kind=page_kind,
                        summary=str(op.get("summary", "")),
                        body_md=body_md,
                        claims=[
                            c for c in (op.get("claims") or []) if isinstance(c, dict)
                        ],
                        aliases=[
                            str(a)
                            for a in (op.get("aliases") or [])
                            if isinstance(a, str) and a.strip()
                        ],
                        source_refs=source_refs,
                        author_kind="compiler",
                        author_ref="system:wiki",
                        change_summary=str(
                            op.get("change_summary", "Incremental compile")
                        ),
                        source_event_seq=source_event_seq,
                    ),
                )
                pages_updated += 1
            except (WikiPolicyError, ValueError) as err:
                logger.info("Skipping compiler op for %r: %s", slug, err)
                skipped_policy += 1

        await self._record_lint_proposals(user_id, plan.get("lint_proposals", []))
        return pages_updated, skipped_policy

    async def _record_lint_proposals(self, user_id: int, raw_issues: Any) -> None:
        if not isinstance(raw_issues, list) or not raw_issues:
            return
        now = _now_ms()
        async with self._session_manager.session() as session:
            for item in raw_issues:
                if not isinstance(item, dict):
                    continue
                issue_type = str(item.get("issue_type", "contradiction"))[:48]
                desc = str(item.get("description", "")).strip()
                if not desc:
                    continue
                dedup_key = _make_dedup_key(f"llm:{issue_type}:{desc}")
                existing = (
                    await session.execute(
                        select(WikiLintIssueDO).where(
                            WikiLintIssueDO.user_id == user_id,
                            WikiLintIssueDO.dedup_key == dedup_key,
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    session.add(
                        WikiLintIssueDO(
                            user_id=user_id,
                            dedup_key=dedup_key,
                            issue_type=issue_type,
                            severity=str(item.get("severity", "warn"))[:16],
                            description=desc,
                            proposal_json=(
                                item.get("proposal")
                                if isinstance(item.get("proposal"), dict)
                                else None
                            ),
                            status="open",
                            create_time=now,
                            update_time=now,
                        )
                    )
            await session.commit()

    async def _get_or_create_checkpoint(self, user_id: int) -> WikiCheckpointDO:
        async with self._session_manager.session() as session:
            cp = (
                await session.execute(
                    select(WikiCheckpointDO).where(WikiCheckpointDO.user_id == user_id)
                )
            ).scalar_one_or_none()
            if cp is None:
                cp = WikiCheckpointDO(user_id=user_id, update_time=_now_ms())
                session.add(cp)
                await session.commit()
            return cp

    async def _update_checkpoint(
        self,
        user_id: int,
        *,
        last_sync_token: str | None = None,
        pending_delta: int = 0,
        reset_lint: bool = False,
        backfill_file_cursor: int | None = None,
        status: str | None = None,
        last_error: str | None = None,
    ) -> None:
        now = _now_ms()
        async with self._session_manager.session() as session:
            cp = (
                await session.execute(
                    select(WikiCheckpointDO).where(WikiCheckpointDO.user_id == user_id)
                )
            ).scalar_one_or_none()
            if cp is None:
                cp = WikiCheckpointDO(user_id=user_id, update_time=now)
                session.add(cp)
            if last_sync_token is not None:
                cp.last_sync_token = last_sync_token
            if pending_delta:
                cp.pending_events_since_lint += pending_delta
            if reset_lint:
                cp.pending_events_since_lint = 0
                cp.last_lint_time = now
            if backfill_file_cursor is not None:
                cp.backfill_file_cursor = backfill_file_cursor
            if status is not None:
                cp.status = status
            cp.last_error = last_error[:512] if last_error else None
            cp.update_time = now
            await session.commit()


WIKI_COMPILER_KEY: web.AppKey[WikiCompilerWorker] = web.AppKey("wiki_compiler")
