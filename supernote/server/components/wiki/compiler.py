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
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from aiohttp import web
from sqlalchemy import select, update

from supernote.models.events import DomainEventType
from supernote.server.ai.base import AIError
from supernote.server.ai.models.text import TextGenerationModel
from supernote.server.components.events.service import EventLogService
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.schedule import ScheduleTaskDO
from supernote.server.db.models.wiki import (
    WikiCheckpointDO,
    WikiLintIssueDO,
    WikiSourceRefDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import (
    DomainEventRecorded,
    LocalEventBus,
    VfsItemPurgedEvent,
)
from supernote.server.exceptions import CursorExpiredError
from supernote.server.metrics import AIStage
from supernote.server.utils.prompt_loader import PROMPT_LOADER, PromptId

from .config import WikiConfig
from .models import (
    VALID_PAGE_KINDS,
    WikiLintIssueDTO,
    WikiPolicyError,
    WikiSourceRefDTO,
    WikiUpsertInput,
)
from .service import WikiService, _make_dedup_key

__all__ = [
    "WIKI_COMPILER_KEY",
    "WIKI_COMPILE_SCHEMA",
    "WIKI_LINT_SCHEMA",
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

WIKI_COMPILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "page_ops": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "title": {"type": "string"},
                    "page_kind": {"type": "string"},
                    "summary": {"type": "string"},
                    "body_md": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "claims": {"type": "array", "items": {"type": "object"}},
                    "source_refs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source_type": {"type": "string"},
                                "source_key": {"type": "string"},
                                "file_id": {"type": ["integer", "null"]},
                            },
                            "required": ["source_type", "source_key"],
                        },
                    },
                    "change_summary": {"type": "string"},
                },
                "required": ["slug", "title", "body_md"],
            },
        },
        "lint_proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue_type": {"type": "string"},
                    "description": {"type": "string"},
                    "proposal": {"type": "object"},
                },
                "required": ["issue_type", "description"],
            },
        },
        "log_entry": {"type": "string"},
    },
    "required": ["page_ops"],
}

WIKI_LINT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue_type": {"type": "string"},
                    "severity": {"type": "string"},
                    "description": {"type": "string"},
                    "proposal": {"type": "object"},
                },
                "required": ["issue_type", "description"],
            },
        }
    },
    "required": ["issues"],
}

_BOUNDARY_TAG_RE = re.compile(
    r"<\s*(/?)\s*(source_diff|linked_context|user_index|candidate_pages|pages_batch|task_snapshots)\b",
    re.IGNORECASE,
)
_PLACEHOLDER_RE = re.compile(r"\{\{([a-z0-9_]+)\}\}")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sanitize_xml_payload(text: str) -> str:
    """Neutralize prompt boundary tags (any case/whitespace) inside untrusted payloads."""
    return _BOUNDARY_TAG_RE.sub(lambda m: f"&lt;{m.group(1)}{m.group(2)}", text)


def _render_prompt_template(template: str, values: dict[str, str]) -> str:
    """Single-pass placeholder substitution preventing chained injection across fields."""
    return _PLACEHOLDER_RE.sub(
        lambda m: values[m.group(1)] if m.group(1) in values else m.group(0),
        template,
    )


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
        """Mark all wiki source refs citing a permanently purged VFS file as deleted."""
        if not self._started:
            return
        now = _now_ms()
        async with self._session_manager.session() as session:
            await session.execute(
                update(WikiSourceRefDO)
                .where(
                    WikiSourceRefDO.user_id == event.user_id,
                    WikiSourceRefDO.file_id == event.item_id,
                )
                .values(is_source_deleted=True, update_time=now)
            )
            await session.commit()

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

            await self._mark_deleted_sources_from_events(user_id, page.events)
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

            linked_context = await self._load_linked_context(user_id, page.events)
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
            prompt = await self._build_compile_prompt(
                user_id, diff_payload, linked_context
            )

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
                prompt = await self._build_compile_prompt(
                    user_id, synthetic_diffs, linked_context={}
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

            pages_json = _sanitize_xml_payload(
                json.dumps(
                    [
                        {
                            "slug": p.slug,
                            "title": p.title,
                            "summary": p.summary,
                            "aliases": p.aliases,
                            "claims": p.claims,
                        }
                        for p in pages
                    ]
                )
            )
            tasks_json = _sanitize_xml_payload(
                json.dumps(
                    [
                        {
                            "task_id": t.task_id,
                            "title": t.title,
                            "status": t.status,
                            "due_time": t.due_time,
                        }
                        for t in tasks
                    ]
                )
            )
            template = PROMPT_LOADER.get_prompt(PromptId.WIKI_LINT)
            prompt = _render_prompt_template(
                template,
                {
                    "pages_batch_json": pages_json,
                    "task_snapshots_json": tasks_json,
                },
            )
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

    async def _build_compile_prompt(
        self,
        user_id: int,
        diff_payload: list[dict[str, Any]],
        linked_context: dict[str, Any],
    ) -> str:
        all_pages = await self._wiki_service.list_pages(user_id, limit=100)
        compact_index = "\n".join(
            f"- [[{p.slug}]] ({p.page_kind}): {p.title} — {p.summary}"
            for p in all_pages
        )
        candidate_pages = [
            {
                "slug": p.slug,
                "title": p.title,
                "page_kind": p.page_kind,
                "edit_policy": p.edit_policy,
                "version": p.version,
                "aliases": p.aliases,
                "body_md": p.body_md[:2000],
            }
            for p in all_pages[:10]
        ]
        template = PROMPT_LOADER.get_prompt(PromptId.WIKI_COMPILE)
        return _render_prompt_template(
            template,
            {
                "compact_index_md": _sanitize_xml_payload(compact_index),
                "candidate_pages_json": _sanitize_xml_payload(
                    json.dumps(candidate_pages)
                ),
                "diff_events_json": _sanitize_xml_payload(json.dumps(diff_payload)),
                "linked_note_and_task_context_json": _sanitize_xml_payload(
                    json.dumps(linked_context)
                ),
            },
        )

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

    async def _mark_deleted_sources_from_events(
        self, user_id: int, events: list[DomainEventRecorded]
    ) -> None:
        now = _now_ms()
        deleted_file_ids: set[int] = set()
        deleted_page_keys: set[str] = set()
        deleted_task_ids: set[str] = set()
        for ev in events:
            if (
                ev.event_type == DomainEventType.FILE_DELETED.value
                and ev.related_file_id
            ):
                deleted_file_ids.add(ev.related_file_id)
            elif (
                ev.event_type == DomainEventType.NOTE_PAGES_DELTA.value
                and ev.related_file_id
            ):
                for pid in ev.payload.get("deleted_pages") or []:
                    deleted_page_keys.add(f"{ev.related_file_id}:{pid}")
            elif ev.event_type == DomainEventType.SCHEDULE_TASK_DELETED.value:
                deleted_task_ids.add(ev.entity_id)

        if not (deleted_file_ids or deleted_page_keys or deleted_task_ids):
            return
        async with self._session_manager.session() as session:
            if deleted_file_ids:
                await session.execute(
                    update(WikiSourceRefDO)
                    .where(
                        WikiSourceRefDO.user_id == user_id,
                        WikiSourceRefDO.file_id.in_(deleted_file_ids),
                    )
                    .values(is_source_deleted=True, update_time=now)
                )
            if deleted_page_keys:
                await session.execute(
                    update(WikiSourceRefDO)
                    .where(
                        WikiSourceRefDO.user_id == user_id,
                        WikiSourceRefDO.source_type == "note_page",
                        WikiSourceRefDO.source_key.in_(deleted_page_keys),
                    )
                    .values(is_source_deleted=True, update_time=now)
                )
            if deleted_task_ids:
                await session.execute(
                    update(WikiSourceRefDO)
                    .where(
                        WikiSourceRefDO.user_id == user_id,
                        WikiSourceRefDO.source_type == "schedule_task",
                        WikiSourceRefDO.source_key.in_(deleted_task_ids),
                    )
                    .values(is_source_deleted=True, update_time=now)
                )
            await session.commit()

    async def _load_linked_context(
        self, user_id: int, events: list[DomainEventRecorded]
    ) -> dict[str, Any]:
        task_ids = {ev.entity_id for ev in events if ev.entity_type == "schedule_task"}
        file_ids = {
            ev.related_file_id
            for ev in events
            if ev.related_file_id is not None and ev.entity_type == "schedule_task"
        }
        if not task_ids and not file_ids:
            return {}

        async with self._session_manager.session() as session:
            tasks_ctx: list[dict[str, Any]] = []
            if task_ids:
                rows = (
                    (
                        await session.execute(
                            select(ScheduleTaskDO).where(
                                ScheduleTaskDO.user_id == user_id,
                                ScheduleTaskDO.task_id.in_(task_ids),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                tasks_ctx = [
                    {
                        "task_id": t.task_id,
                        "title": t.title,
                        "detail": t.detail,
                        "status": t.status,
                        "importance": t.importance,
                        "recurrence": t.recurrence,
                        "due_time": t.due_time,
                        "completed_time": t.completed_time,
                    }
                    for t in rows
                ]

            pages_ctx: list[dict[str, Any]] = []
            if file_ids:
                # Strict tenant join: NotePageContentDO has no user_id column.
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
                            .limit(10)
                        )
                    )
                    .scalars()
                    .all()
                )
                pages_ctx = [
                    {
                        "file_id": p.file_id,
                        "page_id": p.page_id,
                        "page_index": p.page_index,
                        "text_content": (p.text_content or "")[:1500],
                    }
                    for p in page_rows
                    if not p.is_blank
                ]
            return {"tasks": tasks_ctx, "linked_note_pages": pages_ctx}

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
