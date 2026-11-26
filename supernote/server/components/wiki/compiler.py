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
    flag matching `f_wiki_source_ref.is_source_deleted = True` via
    `WikiService.mark_sources_deleted` so structural lint flags `stale_source`
    instead of leaving silent dead citations.
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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from aiohttp import web
from sqlalchemy import select, update

from supernote.models.events import DomainEventType
from supernote.server.ai.base import AIError
from supernote.server.ai.models.text import TextGenerationModel
from supernote.server.components.events.service import EventLogService
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
    SourceRefTarget,
    WikiCompilePlan,
    WikiLintIssueOp,
    WikiLintProposalOp,
    build_compile_prompt,
    build_lint_prompt,
    get_compile_json_schema,
    get_lint_json_schema,
    parse_compile_plan,
    parse_lint_report,
)
from .service import WikiService, _make_dedup_key
from .source_service import WikiSourceService

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


_VALID_LINT_SEVERITIES: frozenset[str] = frozenset({"info", "warn", "error"})


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
    files_processed: list[str] = field(default_factory=list)
    updated_pages: list[str] = field(default_factory=list)
    remaining_files: int | None = None


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
        self._source_service = WikiSourceService(session_manager)
        self._event_log_service = event_log_service
        self._event_bus = event_bus
        self._text_model = text_model
        self._user_locks: dict[int, asyncio.Lock] = {}
        self._debounce_tasks: dict[int, asyncio.Task[None]] = {}
        self._backfill_tasks: dict[int, asyncio.Task[None]] = {}
        self._backfill_stop_events: dict[int, asyncio.Event] = {}
        self._backfill_starting: set[int] = set()
        self._active_tasks: set[asyncio.Task[None]] = set()
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
        # Reset any stale `backfilling` checkpoints left behind by a prior process exit.
        async with self._session_manager.session() as session:
            await session.execute(
                update(WikiCheckpointDO)
                .where(WikiCheckpointDO.status == "backfilling")
                .values(status="idle", update_time=_now_ms())
            )
            await session.commit()
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
        """Cancel pending debounce timers and active compile tasks idempotently."""
        self._started = False
        for ev in self._backfill_stop_events.values():
            ev.set()
        tasks = (
            list(self._debounce_tasks.values())
            + list(self._backfill_tasks.values())
            + list(self._active_tasks)
        )
        self._debounce_tasks.clear()
        self._backfill_tasks.clear()
        self._backfill_stop_events.clear()
        self._active_tasks.clear()
        unique_tasks = list(dict.fromkeys(tasks))
        for task in unique_tasks:
            task.cancel()
        if unique_tasks:
            await asyncio.gather(*unique_tasks, return_exceptions=True)

    async def _on_event_recorded(self, event: DomainEventRecorded) -> None:
        if not self._started or event.event_type not in WIKI_RELEVANT_EVENT_TYPES:
            return
        self._schedule_user_compile(event.user_id)

    async def _on_vfs_purged(self, event: VfsItemPurgedEvent) -> None:
        """Mark wiki source refs citing a permanently purged VFS file as deleted."""
        if not self._started:
            return
        async with self._lock_for_user(event.user_id):
            await self._wiki_service.mark_sources_deleted(
                event.user_id, file_ids={event.item_id}
            )

    def _schedule_user_compile(self, user_id: int) -> None:
        if existing := self._debounce_tasks.get(user_id):
            existing.cancel()

        async def _delayed() -> None:
            current = asyncio.current_task()
            try:
                if self._config.debounce_seconds > 0:
                    await asyncio.sleep(self._config.debounce_seconds)
                # Detach from `_debounce_tasks` before compiling so newly arriving
                # events schedule a follow-up instead of cancelling in-flight work.
                if self._debounce_tasks.get(user_id) is current:
                    self._debounce_tasks.pop(user_id, None)
                if not self._started:
                    return
                await self.compile_user_delta(user_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Wiki incremental compile failed for user %s", user_id)
            finally:
                if self._debounce_tasks.get(user_id) is current:
                    self._debounce_tasks.pop(user_id, None)
                if current is not None:
                    self._active_tasks.discard(current)

        task = asyncio.create_task(_delayed())
        self._debounce_tasks[user_id] = task
        self._active_tasks.add(task)

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
                idle_status = (
                    "backfilling" if self.is_backfill_running(user_id) else "idle"
                )
                if page.next_sync_token != cp.last_sync_token:
                    await self._update_checkpoint(
                        user_id,
                        last_sync_token=page.next_sync_token,
                        status=idle_status,
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
                    status=idle_status,
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

            linked_context = await self._source_service.load_linked_context(
                user_id, page.events
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
            all_pages = await self._wiki_service.list_pages(user_id, limit=500)
            built = build_compile_prompt(
                all_pages,
                diff_payload,
                linked_context,
                max_pages_per_batch=self._config.max_pages_per_batch,
            )

            # Execute LLM HTTP call strictly outside any open SQLite session.
            try:
                raw_plan = await self._text_model.generate_json(
                    built.prompt,
                    response_schema=get_compile_json_schema(),
                    schema_name="wiki_compile_plan",
                    stage=AIStage.WIKI_COMPILE,
                )
                plan = parse_compile_plan(raw_plan)
            except (AIError, ValueError, TypeError, LookupError) as err:
                await self._update_checkpoint(
                    user_id, status="error", last_error=str(err)
                )
                raise

            updated_slugs, skipped_policy = await self._apply_compile_plan(
                user_id,
                plan,
                source_event_seq=max_seq,
                source_handles=built.source_handles,
            )
            if updated_slugs:
                await self._wiki_service.sync_index_page(user_id)
            issues = await self._wiki_service.run_structural_lint(user_id)
            next_status = "backfilling" if self.is_backfill_running(user_id) else "idle"
            await self._update_checkpoint(
                user_id,
                last_sync_token=page.next_sync_token,
                pending_delta=len(page.events),
                status=next_status,
                last_error=None,
            )
            if page.has_more and self._started and self._config.auto_compile:
                self._schedule_user_compile(user_id)
            return WikiCompileResult(
                events_processed=len(page.events),
                pages_updated=len(updated_slugs),
                skipped_policy_pages=skipped_policy,
                lint_issues_open=len(issues),
                status=next_status,
                updated_pages=updated_slugs,
            )

    async def run_backfill(
        self,
        user_id: int,
        *,
        max_files: int = 5,
        _final_status: str = "idle",
    ) -> WikiCompileResult:
        """Compile existing `.note` OCR transcripts newest-first in bounded chunks."""
        async with self._lock_for_user(user_id):
            if self._text_model is None:
                await self._update_checkpoint(
                    user_id,
                    status="paused",
                    last_error="Text generation model not configured",
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

            cp = await self._get_or_create_checkpoint(user_id)
            (
                synthetic_diffs,
                next_cursor,
            ) = await self._source_service.list_backfill_batch(
                user_id,
                before_file_id=cp.backfill_file_cursor,
                max_files=max_files,
            )
            if next_cursor is None:
                issues = await self._wiki_service.list_lint_issues(
                    user_id, status="open"
                )
                await self._update_checkpoint(user_id, status="idle", last_error=None)
                return WikiCompileResult(
                    events_processed=0,
                    pages_updated=0,
                    skipped_policy_pages=0,
                    lint_issues_open=len(issues),
                    status="idle",
                    remaining_files=0,
                )

            files_processed = list(
                dict.fromkeys(
                    str(diff["payload"]["file_path"])
                    for diff in synthetic_diffs
                    if diff.get("payload", {}).get("file_path")
                )
            )
            updated_slugs: list[str] = []
            skipped_policy = 0
            if synthetic_diffs:
                task_rows = await self._source_service.list_task_snapshots(
                    user_id, limit=50
                )
                linked_context: dict[str, object] = {}
                if task_rows:
                    linked_context["tasks"] = [
                        {
                            "task_id": t.task_id,
                            "title": t.title,
                            "detail": t.detail,
                            "status": t.status,
                            "importance": t.importance,
                            "due_time": t.due_time,
                            "completed_time": t.completed_time,
                        }
                        for t in task_rows
                    ]
                backfill_page_budget = max(
                    self._config.max_pages_per_batch, max_files * 2, 10
                )
                window_size = self._config.max_source_pages_per_turn
                for start in range(0, len(synthetic_diffs), window_size):
                    window_diffs = synthetic_diffs[start : start + window_size]
                    all_pages = await self._wiki_service.list_pages(user_id, limit=500)
                    built = build_compile_prompt(
                        all_pages,
                        window_diffs,
                        linked_context=linked_context,
                        max_pages_per_batch=backfill_page_budget,
                    )
                    try:
                        raw_plan = await self._text_model.generate_json(
                            built.prompt,
                            response_schema=get_compile_json_schema(),
                            schema_name="wiki_compile_plan",
                            stage=AIStage.WIKI_COMPILE,
                        )
                        plan = parse_compile_plan(raw_plan)
                    except (AIError, ValueError, TypeError, LookupError) as err:
                        await self._update_checkpoint(
                            user_id, status="error", last_error=str(err)
                        )
                        raise
                    window_slugs, window_skipped = await self._apply_compile_plan(
                        user_id,
                        plan,
                        source_event_seq=None,
                        max_pages=backfill_page_budget,
                        source_handles=built.source_handles,
                    )
                    updated_slugs.extend(window_slugs)
                    skipped_policy += window_skipped
                    if window_slugs:
                        await self._wiki_service.sync_index_page(user_id)
                updated_slugs = list(dict.fromkeys(updated_slugs))

            issues = await self._wiki_service.run_structural_lint(user_id)
            remaining_files, _ = await self._source_service.count_backfill_progress(
                user_id, before_file_id=next_cursor
            )
            resolved_status = "idle" if remaining_files == 0 else _final_status
            await self._update_checkpoint(
                user_id,
                backfill_file_cursor=next_cursor,
                status=resolved_status,
                last_error=None,
            )
            return WikiCompileResult(
                events_processed=len(synthetic_diffs),
                pages_updated=len(updated_slugs),
                skipped_policy_pages=skipped_policy,
                lint_issues_open=len(issues),
                status=resolved_status,
                files_processed=files_processed,
                updated_pages=updated_slugs,
                remaining_files=remaining_files,
            )

    def is_backfill_running(self, user_id: int) -> bool:
        """Return True if a background backfill loop is currently running for `user_id`."""
        task = self._backfill_tasks.get(user_id)
        return user_id in self._backfill_starting or (
            task is not None and not task.done()
        )

    async def start_backfill_job(
        self, user_id: int, *, max_files_per_turn: int = 1
    ) -> WikiCompileResult:
        """Start a server-side background backfill loop processing all remaining notebooks."""
        if self._text_model is None:
            await self._update_checkpoint(
                user_id,
                status="paused",
                last_error="Text generation model not configured",
            )
            issues = await self._wiki_service.list_lint_issues(user_id, status="open")
            return WikiCompileResult(
                events_processed=0,
                pages_updated=0,
                skipped_policy_pages=0,
                lint_issues_open=len(issues),
                status="paused",
            )

        if self.is_backfill_running(user_id):
            cp = await self._get_or_create_checkpoint(user_id)
            remaining, _ = await self._source_service.count_backfill_progress(
                user_id, before_file_id=cp.backfill_file_cursor
            )
            issues = await self._wiki_service.list_lint_issues(user_id, status="open")
            return WikiCompileResult(
                events_processed=0,
                pages_updated=0,
                skipped_policy_pages=0,
                lint_issues_open=len(issues),
                status="backfilling",
                remaining_files=remaining,
            )

        # Reserve synchronously before any await so concurrent calls cannot spawn duplicate tasks.
        self._backfill_starting.add(user_id)
        try:
            cp = await self._get_or_create_checkpoint(user_id)
            remaining, _ = await self._source_service.count_backfill_progress(
                user_id, before_file_id=cp.backfill_file_cursor
            )
            issues = await self._wiki_service.list_lint_issues(user_id, status="open")

            if remaining == 0:
                await self._update_checkpoint(user_id, status="idle", last_error=None)
                return WikiCompileResult(
                    events_processed=0,
                    pages_updated=0,
                    skipped_policy_pages=0,
                    lint_issues_open=len(issues),
                    status="idle",
                    remaining_files=0,
                )

            await self._update_checkpoint(
                user_id, status="backfilling", last_error=None
            )
            stop_event = asyncio.Event()
            self._backfill_stop_events[user_id] = stop_event
            capped_files = max(1, min(max_files_per_turn, 20))

            async def _loop() -> None:
                current = asyncio.current_task()
                errored = False
                paused = False
                try:
                    while not stop_event.is_set():
                        res = await self.run_backfill(
                            user_id,
                            max_files=capped_files,
                            _final_status="backfilling",
                        )
                        if res.status == "paused":
                            paused = True
                            break
                        if (res.remaining_files or 0) == 0:
                            break
                        if res.events_processed == 0 and res.pages_updated == 0:
                            break
                except asyncio.CancelledError:
                    raise
                except Exception:
                    errored = True
                    logger.exception(
                        "Background wiki backfill failed for user %s", user_id
                    )
                finally:
                    if self._backfill_tasks.get(user_id) is current:
                        self._backfill_tasks.pop(user_id, None)
                    if self._backfill_stop_events.get(user_id) is stop_event:
                        self._backfill_stop_events.pop(user_id, None)
                    if current is not None:
                        self._active_tasks.discard(current)
                    if not errored and not paused:
                        try:
                            await self._update_checkpoint(
                                user_id, status="idle", last_error=None
                            )
                        except Exception:
                            logger.debug(
                                "Skipping final idle checkpoint update for user %s",
                                user_id,
                            )

            task = asyncio.create_task(_loop())
            self._backfill_tasks[user_id] = task
            self._active_tasks.add(task)
            return WikiCompileResult(
                events_processed=0,
                pages_updated=0,
                skipped_policy_pages=0,
                lint_issues_open=len(issues),
                status="backfilling",
                remaining_files=remaining,
            )
        finally:
            self._backfill_starting.discard(user_id)

    async def stop_backfill_job(self, user_id: int) -> WikiCompileResult:
        """Signal an active background backfill job to stop after its current notebook."""
        running = self.is_backfill_running(user_id)
        if stop_event := self._backfill_stop_events.get(user_id):
            stop_event.set()
        cp = await self._get_or_create_checkpoint(user_id)
        if not running and cp.status == "backfilling":
            await self._update_checkpoint(user_id, status="idle", last_error=None)
        remaining, _ = await self._source_service.count_backfill_progress(
            user_id, before_file_id=cp.backfill_file_cursor
        )
        issues = await self._wiki_service.list_lint_issues(user_id, status="open")
        return WikiCompileResult(
            events_processed=0,
            pages_updated=0,
            skipped_policy_pages=0,
            lint_issues_open=len(issues),
            status="stopping" if running else "idle",
            remaining_files=remaining,
        )

    async def reset_backfill(self, user_id: int) -> WikiCompileResult:
        """Reset `backfill_file_cursor` so all OCR'd notebooks are queued for backfill again."""
        if self.is_backfill_running(user_id):
            raise ValueError("Stop the running backfill before resetting.")
        async with self._lock_for_user(user_id):
            await self._update_checkpoint(
                user_id,
                clear_backfill_cursor=True,
                status="idle",
                last_error=None,
            )
            remaining, _ = await self._source_service.count_backfill_progress(
                user_id, before_file_id=None
            )
            issues = await self._wiki_service.list_lint_issues(user_id, status="open")
            return WikiCompileResult(
                events_processed=0,
                pages_updated=0,
                skipped_policy_pages=0,
                lint_issues_open=len(issues),
                status="idle",
                remaining_files=remaining,
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

            tasks = await self._source_service.list_task_snapshots(user_id, limit=50)
            prompt = build_lint_prompt(pages, tasks)
            try:
                raw_report = await self._text_model.generate_json(
                    prompt,
                    response_schema=get_lint_json_schema(),
                    schema_name="wiki_lint_report",
                    stage=AIStage.WIKI_LINT,
                )
                report = parse_lint_report(raw_report)
            except (AIError, ValueError, TypeError, LookupError) as err:
                await self._update_checkpoint(
                    user_id, status="error", last_error=str(err)
                )
                raise
            await self._record_lint_proposals(user_id, report.issues)
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
        plan: WikiCompilePlan,
        *,
        source_event_seq: int | None,
        max_pages: int | None = None,
        source_handles: Mapping[str, SourceRefTarget] | None = None,
    ) -> tuple[list[str], int]:
        updated_slugs: list[str] = []
        skipped_policy = 0
        page_cap = (
            max_pages if max_pages is not None else self._config.max_pages_per_batch
        )
        normalized_handles: dict[str, SourceRefTarget] = {}
        known_raw_targets: dict[tuple[str, str], SourceRefTarget] = {}
        if source_handles:
            for handle, target in source_handles.items():
                normalized_handles[handle.lower()] = target
                known_raw_targets[(str(target.source_type), target.source_key)] = target

        non_index_ops = [
            op
            for op in plan.page_ops
            if op.slug.strip().lower() != "index" and op.page_kind != "index"
        ]
        for op in non_index_ops[:page_cap]:
            slug = op.slug.strip()
            title = op.title.strip()
            if not slug or not title:
                continue
            page_kind = op.page_kind if op.page_kind in VALID_PAGE_KINDS else "topic"
            source_refs: list[WikiSourceRefDTO] = []
            seen_refs: set[tuple[str, str]] = set()
            for ref in op.source_refs:
                if not ref.source_type or not ref.source_key:
                    continue
                clean_key = ref.source_key.strip()
                redundant_prefix = f"{ref.source_type}:"
                if clean_key.startswith(redundant_prefix):
                    clean_key = clean_key[len(redundant_prefix) :]
                if not clean_key:
                    continue
                resolved_type = ref.source_type
                resolved_key = clean_key
                resolved_file_id = ref.file_id
                if source_handles is not None:
                    target = normalized_handles.get(
                        clean_key.lower()
                    ) or known_raw_targets.get((str(ref.source_type), clean_key))
                    if target is None:
                        logger.debug(
                            "Dropping unrecognized source_ref %r on %r",
                            ref.source_key,
                            slug,
                        )
                        continue
                    resolved_type = target.source_type
                    resolved_key = target.source_key
                    resolved_file_id = target.file_id
                dedup_key = (str(resolved_type), resolved_key)
                if dedup_key in seen_refs:
                    continue
                seen_refs.add(dedup_key)
                source_refs.append(
                    WikiSourceRefDTO(
                        source_type=resolved_type,
                        source_key=resolved_key,
                        file_id=resolved_file_id,
                        last_event_seq=source_event_seq,
                    )
                )
            resolved_claims: list[dict[str, object]] = []
            for claim in op.claims:
                claim_dict = claim.to_dict()
                superseded = str(claim_dict.get("superseded_by_source") or "").strip()
                if superseded and source_handles is not None:
                    target = normalized_handles.get(superseded.lower())
                    if target is not None:
                        claim_dict["superseded_by_source"] = target.source_key
                resolved_claims.append(claim_dict)
            try:
                page = await self._wiki_service.upsert_page(
                    user_id,
                    WikiUpsertInput(
                        slug=slug,
                        title=title,
                        page_kind=page_kind,
                        summary=op.summary,
                        body_md=op.body_md,
                        claims=resolved_claims,
                        aliases=[a for a in op.aliases if a.strip()],
                        source_refs=source_refs,
                        author_kind="compiler",
                        author_ref="system:wiki",
                        change_summary=op.change_summary or "Incremental compile",
                        source_event_seq=source_event_seq,
                    ),
                )
                updated_slugs.append(page.slug)
            except (WikiPolicyError, ValueError) as err:
                logger.info("Skipping compiler op for %r: %s", slug, err)
                skipped_policy += 1

        await self._record_lint_proposals(user_id, plan.lint_proposals)
        return updated_slugs, skipped_policy

    async def _record_lint_proposals(
        self,
        user_id: int,
        issues: Sequence[WikiLintProposalOp | WikiLintIssueOp],
    ) -> None:
        if not issues:
            return
        now = _now_ms()
        async with self._session_manager.session() as session:
            for item in issues:
                issue_type = (item.issue_type or "contradiction")[:48]
                desc = item.description.strip()
                if not desc:
                    continue
                raw_severity = (
                    item.severity if isinstance(item, WikiLintIssueOp) else "warn"
                )
                severity = (
                    raw_severity if raw_severity in _VALID_LINT_SEVERITIES else "warn"
                )
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
                            severity=severity,
                            description=desc,
                            proposal_json=(
                                item.proposal.to_dict()
                                if item.proposal is not None
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

        await self._wiki_service.mark_sources_deleted(
            user_id,
            file_ids=deleted_file_ids,
            note_page_keys=deleted_page_keys,
            task_ids=deleted_task_ids,
        )

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
        clear_backfill_cursor: bool = False,
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
            if clear_backfill_cursor:
                cp.backfill_file_cursor = None
            elif backfill_file_cursor is not None:
                cp.backfill_file_cursor = backfill_file_cursor
            if status is not None:
                cp.status = status
            cp.last_error = last_error[:512] if last_error else None
            cp.update_time = now
            await session.commit()


WIKI_COMPILER_KEY: web.AppKey[WikiCompilerWorker] = web.AppKey("wiki_compiler")
