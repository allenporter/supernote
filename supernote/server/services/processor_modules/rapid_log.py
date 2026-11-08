"""Processor module for indexing Rapid Logging entries and syncing tasks into ScheduleService."""

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select

from supernote.models.base import TaskType
from supernote.models.schedule import ScheduleTaskLinkDTO
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    RapidLogEntryDO,
)
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.services.schedule import (
    MAX_DETAIL_LENGTH,
    MAX_TITLE_LENGTH,
    ScheduleService,
)
from supernote.server.utils.hashing import get_md5_hash
from supernote.server.utils.note_content import infer_page_date
from supernote.server.utils.rapid_log import (
    RapidLogKind,
    RapidLogTaskState,
    parse_rapid_log,
)

__all__ = [
    "DEFAULT_NOTES_TASK_GROUP_TITLE",
    "RapidLogModule",
]

logger = logging.getLogger(__name__)

DEFAULT_NOTES_TASK_GROUP_TITLE = "From Notes"

_WHITESPACE_RE = re.compile(r"\s+")
_TRAILING_PUNCT_RE = re.compile(r"[.;,:]+$")
_HEADER_DATE_RE = re.compile(r"(?<!\d)(\d{4})[-/](\d{2})[-/](\d{2})(?!\d)")

_OPEN_TASK_STATES = frozenset(
    {
        RapidLogTaskState.INCOMPLETE,
        RapidLogTaskState.MIGRATED_FORWARD,
        RapidLogTaskState.MIGRATED_SCHEDULED,
    }
)
_MIGRATED_TASK_VALUES = frozenset(
    {
        RapidLogTaskState.MIGRATED_FORWARD.value,
        RapidLogTaskState.MIGRATED_SCHEDULED.value,
    }
)


@dataclass(slots=True)
class _ExtractedEntry:
    """Normalized Rapid Log entry extracted from a single page."""

    kind: RapidLogKind
    text: str
    normalized_text: str
    task_state: RapidLogTaskState | None
    is_starred: bool
    is_cancelled: bool
    has_explicit_bullet: bool
    detail: str | None


def _normalize_entry_text(text: str) -> str:
    """Normalize entry text for idempotent matching across OCR runs and page migrations."""
    cleaned = _WHITESPACE_RE.sub(" ", text.strip())
    cleaned = _TRAILING_PUNCT_RE.sub("", cleaned).strip()
    return cleaned.lower()


def _format_schedule_fields(text: str, detail: str | None) -> tuple[str, str]:
    """Bound title and detail to ScheduleService limits without losing long OCR text."""
    if len(text) <= MAX_TITLE_LENGTH:
        return text, (detail or "")[:MAX_DETAIL_LENGTH]

    truncated_title = f"{text[: MAX_TITLE_LENGTH - 1].rstrip()}…"
    full_detail = f"{text}\n\n{detail}" if detail else text
    return truncated_title, full_detail[:MAX_DETAIL_LENGTH]


def _extract_page_entries(text_content: str | None) -> list[_ExtractedEntry]:
    """Extract and deduplicate Rapid Log entries (`TASK`, `EVENT`, `NOTE`) on a single page."""
    deduped: dict[tuple[RapidLogKind, str], _ExtractedEntry] = {}
    for item in parse_rapid_log(text_content):
        norm_text = _normalize_entry_text(item.text)
        if not norm_text:
            continue
        key = (item.kind, norm_text)
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = _ExtractedEntry(
                kind=item.kind,
                text=item.text,
                normalized_text=norm_text,
                task_state=item.task_state,
                is_starred=item.is_starred,
                is_cancelled=item.is_cancelled,
                has_explicit_bullet=item.has_explicit_bullet,
                detail=item.detail,
            )
            continue

        existing.has_explicit_bullet = (
            existing.has_explicit_bullet or item.has_explicit_bullet
        )
        # Do not let a crossed-out duplicate overwrite a live entry on the same page
        if not existing.is_cancelled and item.is_cancelled:
            continue
        if existing.is_cancelled and not item.is_cancelled:
            existing.text = item.text
            existing.task_state = item.task_state
            existing.is_starred = item.is_starred
            existing.is_cancelled = False
            existing.detail = item.detail
            continue

        existing.text = item.text
        existing.task_state = item.task_state
        existing.is_starred = existing.is_starred or item.is_starred
        existing.is_cancelled = item.is_cancelled
        if item.detail:
            existing.detail = (
                f"{existing.detail}\n{item.detail}" if existing.detail else item.detail
            )
    return list(deduped.values())


def _resolve_bare_strikethroughs(
    page_id: str,
    entries: list[_ExtractedEntry],
    existing_by_key: dict[tuple[str, str, str], RapidLogEntryDO],
    open_notebook_task_norms: set[str],
) -> list[_ExtractedEntry]:
    """Resolve bulletless `~~...~~` lines against existing entries and drop crossed-out prose."""
    resolved: dict[tuple[RapidLogKind, str], _ExtractedEntry] = {}
    for entry in entries:
        if not entry.has_explicit_bullet:
            matched_kind: RapidLogKind | None = None
            for candidate_kind in (
                RapidLogKind.TASK,
                RapidLogKind.EVENT,
                RapidLogKind.NOTE,
            ):
                if (
                    page_id,
                    candidate_kind.value,
                    entry.normalized_text,
                ) in existing_by_key:
                    matched_kind = candidate_kind
                    break
            if matched_kind is None:
                if entry.normalized_text in open_notebook_task_norms:
                    matched_kind = RapidLogKind.TASK
                else:
                    # Plain crossed-out prose sentence that was never a Rapid Log item
                    continue
            if matched_kind != RapidLogKind.TASK:
                prev_row = existing_by_key[
                    (page_id, matched_kind.value, entry.normalized_text)
                ]
                entry = _ExtractedEntry(
                    kind=matched_kind,
                    text=entry.text,
                    normalized_text=entry.normalized_text,
                    task_state=None,
                    is_starred=prev_row.is_starred or entry.is_starred,
                    is_cancelled=True,
                    has_explicit_bullet=False,
                    detail=entry.detail,
                )

        key = (entry.kind, entry.normalized_text)
        prev = resolved.get(key)
        if prev is None or (prev.is_cancelled and not entry.is_cancelled):
            resolved[key] = entry
    return list(resolved.values())


def _build_link_b64(
    file_path: str,
    file_id: int,
    page: NotePageContentDO,
    task_title: str,
) -> str:
    """Build a Base64-encoded ScheduleTaskLinkDTO deep-link for a notebook page."""
    dto = ScheduleTaskLinkDTO(
        app_name="Note",
        path=file_path,
        page=page.page_index + 1,
        file_id=str(file_id),
        page_id=page.page_id,
        task_title=task_title,
    )
    return dto.to_b64()


def _infer_header_date(text_content: str | None) -> datetime | None:
    """Extract an explicit YYYY-MM-DD / YYYY/MM/DD date from leading page header lines."""
    if not text_content:
        return None
    checked = 0
    for raw_line in text_content.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        checked += 1
        if checked > 5:
            break
        # Stop scanning headers once the bullet list begins, unless it's a Markdown '#' heading
        if not stripped.startswith("#") and parse_rapid_log(stripped):
            break
        match = _HEADER_DATE_RE.search(stripped)
        if match:
            year, month, day = (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
            )
            if 1970 <= year <= 2100:
                try:
                    return datetime(year, month, day)
                except ValueError:
                    continue
    return None


def _infer_page_date_ms(page_id: str, text_content: str | None = None) -> int | None:
    """Infer page date (ms UTC) from explicit header date, falling back to `page_id`."""
    inferred_dt = _infer_header_date(text_content) or infer_page_date(page_id)
    if inferred_dt is None:
        return None
    return int(inferred_dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _compute_entry_hash(
    entry: _ExtractedEntry,
    page_index: int,
    page_date_ms: int | None,
    file_path: str,
) -> str:
    """Compute a deterministic hash of the Rapid Log entry and its page anchor."""
    payload = json.dumps(
        [
            entry.kind.value,
            entry.text,
            entry.task_state.value if entry.task_state is not None else None,
            entry.is_starred,
            entry.is_cancelled,
            entry.detail,
            page_index,
            page_date_ms,
            file_path,
        ],
        ensure_ascii=False,
    )
    return get_md5_hash(payload)


def _build_entry_row(
    *,
    existing: RapidLogEntryDO | None,
    user_id: int,
    file_id: int,
    page_id: str,
    page_index: int,
    entry: _ExtractedEntry,
    page_date_ms: int | None,
    content_hash: str,
    schedule_task_id: str | None,
    now_ms: int,
) -> RapidLogEntryDO:
    """Construct or update a detached RapidLogEntryDO instance with the latest entry state."""
    task_state_val = entry.task_state.value if entry.task_state is not None else None
    if existing is None:
        return RapidLogEntryDO(
            user_id=user_id,
            file_id=file_id,
            page_id=page_id,
            page_index=page_index,
            kind=entry.kind.value,
            normalized_text=entry.normalized_text,
            text=entry.text,
            detail=entry.detail,
            task_state=task_state_val,
            is_starred=entry.is_starred,
            is_cancelled=entry.is_cancelled,
            page_date_ms=page_date_ms,
            content_hash=content_hash,
            schedule_task_id=schedule_task_id,
            create_time=now_ms,
            update_time=now_ms,
        )

    existing.page_index = page_index
    existing.text = entry.text
    existing.detail = entry.detail
    existing.task_state = task_state_val
    existing.is_starred = entry.is_starred
    existing.is_cancelled = entry.is_cancelled
    existing.page_date_ms = page_date_ms
    existing.content_hash = content_hash
    existing.schedule_task_id = schedule_task_id
    existing.update_time = now_ms
    return existing


def _compute_in_place_task_updates(
    *,
    row: RapidLogEntryDO,
    entry: _ExtractedEntry,
    remote: Any,
    file_path: str,
    file_id: int,
    page: NotePageContentDO,
    page_date_ms: int | None,
    now_ms: int,
) -> dict[str, Any]:
    """Compute edge-triggered ScheduleService updates so digital edits are never clobbered."""
    updates: dict[str, Any] = {}
    prev_task_state = row.task_state

    if (
        entry.task_state == RapidLogTaskState.COMPLETED
        and prev_task_state != RapidLogTaskState.COMPLETED.value
        and remote.status != "completed"
    ):
        updates["status"] = "completed"
        updates["completed_time"] = now_ms
    elif (
        entry.task_state in _OPEN_TASK_STATES
        and prev_task_state == RapidLogTaskState.COMPLETED.value
        and remote.status == "completed"
    ):
        updates["status"] = "needsAction"
        updates["completed_time"] = 0

    old_sched_title, old_sched_detail = _format_schedule_fields(row.text, row.detail)
    new_sched_title, new_sched_detail = _format_schedule_fields(
        entry.text, entry.detail
    )

    if new_sched_title != old_sched_title and remote.title != new_sched_title:
        updates["title"] = new_sched_title
    if (
        new_sched_detail != old_sched_detail
        and (remote.detail or "") != new_sched_detail
    ):
        updates["detail"] = new_sched_detail
    if entry.is_starred != row.is_starred:
        new_importance = "high" if entry.is_starred else None
        if remote.importance != new_importance:
            updates["importance"] = new_importance
    if page_date_ms != row.page_date_ms and remote.due_time != page_date_ms:
        updates["due_time"] = page_date_ms

    link_title = updates.get("title", remote.title or new_sched_title)
    new_links = _build_link_b64(file_path, file_id, page, link_title)
    if remote.links != new_links:
        updates["links"] = new_links

    return updates


class RapidLogModule(ProcessorModule):
    """Post-OCR notebook module that indexes Rapid Log entries and syncs tasks with ScheduleService."""

    def __init__(
        self,
        file_service: FileService,
        schedule_service: ScheduleService,
        enabled: bool = True,
        default_group_title: str = DEFAULT_NOTES_TASK_GROUP_TITLE,
    ) -> None:
        self.file_service = file_service
        self.schedule_service = schedule_service
        self._enabled = enabled
        self.default_group_title = default_group_title

    @property
    def name(self) -> str:
        return "RapidLogModule"

    @property
    def task_type(self) -> TaskType:
        return TaskType.RAPID_LOG_EXTRACTION

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
    ) -> bool:
        """Determine whether notebook-level Rapid Log extraction is needed."""
        if page_index is not None:
            return False

        if not await super().run_if_needed(file_id, session_manager, page_index):
            return False

        async with session_manager.session() as session:
            pages = (
                (
                    await session.execute(
                        select(NotePageContentDO.text_content).where(
                            NotePageContentDO.file_id == file_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            # Only defer when pages exist and OCR has not completed on all of them yet.
            # Zero-page notes (or notes whose pages were all deleted) proceed so stale
            # entries are cleaned up and the global checkpoint is marked COMPLETED.
            if pages and any(text is None for text in pages):
                return False

        return True

    async def cleanup_file(
        self,
        file_id: int,
        user_id: int,
        session_manager: DatabaseSessionManager,
    ) -> None:
        """Delete open synced ScheduleTaskDOs and RapidLogEntryDO rows for a deleted note."""
        async with session_manager.session() as session:
            owned_task_ids = [
                tid
                for tid in (
                    await session.execute(
                        select(RapidLogEntryDO.schedule_task_id).where(
                            RapidLogEntryDO.file_id == file_id,
                            RapidLogEntryDO.user_id == user_id,
                            RapidLogEntryDO.schedule_task_id.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
                if tid is not None
            ]

        for task_id in owned_task_ids:
            remote = await self.schedule_service.get_task(user_id, task_id)
            if remote is not None and remote.status == "needsAction":
                await self.schedule_service.delete_task(user_id, remote.task_id)

        async with session_manager.session() as session:
            await session.execute(
                delete(RapidLogEntryDO).where(
                    RapidLogEntryDO.file_id == file_id,
                    RapidLogEntryDO.user_id == user_id,
                )
            )
            await session.commit()

    async def _get_or_create_target_group_id(self, user_id: int) -> str:
        """Return the task_list_id for the 'From Notes' group, creating it lazily if needed."""
        for group in await self.schedule_service.list_groups(user_id):
            if group.title == self.default_group_title:
                return group.task_list_id
        created = await self.schedule_service.create_group(
            user_id=user_id,
            title=self.default_group_title,
        )
        return created.task_list_id

    async def _persist_rows(
        self,
        session_manager: DatabaseSessionManager,
        rows_to_merge: list[RapidLogEntryDO],
        rows_to_delete: list[RapidLogEntryDO] | None = None,
    ) -> None:
        """Persist RapidLogEntryDO upserts and deletions in an isolated transaction."""
        if not rows_to_merge and not rows_to_delete:
            return
        async with session_manager.session() as session:
            for idx, row in enumerate(rows_to_merge):
                rows_to_merge[idx] = await session.merge(row)
            if rows_to_delete:
                delete_ids = [r.id for r in rows_to_delete if r.id is not None]
                if delete_ids:
                    user_id = rows_to_delete[0].user_id
                    await session.execute(
                        delete(RapidLogEntryDO).where(
                            RapidLogEntryDO.user_id == user_id,
                            RapidLogEntryDO.id.in_(delete_ids),
                        )
                    )
            await session.commit()

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        **kwargs: object,
    ) -> None:
        """Index Rapid Log entries for `file_id` and reconcile TASK items with ScheduleService."""
        logger.info(f"Starting Rapid Log extraction for file_id={file_id}")

        async with session_manager.session() as session:
            file_do = await session.get(UserFileDO, file_id)
            if not file_do or file_do.is_active != "Y":
                logger.debug(
                    f"File {file_id} missing or inactive; skipping Rapid Log extraction."
                )
                return
            user_id = file_do.user_id
            file_name = file_do.file_name

            pages = list(
                (
                    await session.execute(
                        select(NotePageContentDO)
                        .where(NotePageContentDO.file_id == file_id)
                        .order_by(NotePageContentDO.page_index.asc())
                    )
                )
                .scalars()
                .all()
            )
            existing_rows = list(
                (
                    await session.execute(
                        select(RapidLogEntryDO).where(
                            RapidLogEntryDO.file_id == file_id,
                            RapidLogEntryDO.user_id == user_id,
                        )
                    )
                )
                .scalars()
                .all()
            )

        if not pages and not existing_rows:
            return

        file_path = (
            await self.file_service.get_full_path_by_node(user_id, file_id)
            or f"/NOTE/{file_name}"
        )

        entry_map: dict[tuple[str, str, str], RapidLogEntryDO] = {
            (row.page_id, row.kind, row.normalized_text): row for row in existing_rows
        }
        open_notebook_task_norms = {
            row.normalized_text
            for row in existing_rows
            if row.kind == RapidLogKind.TASK.value and row.schedule_task_id is not None
        }

        parsed_pages: list[
            tuple[NotePageContentDO, int | None, list[_ExtractedEntry]]
        ] = [
            (
                page,
                _infer_page_date_ms(page.page_id, page.text_content),
                _resolve_bare_strikethroughs(
                    page.page_id,
                    _extract_page_entries(page.text_content),
                    entry_map,
                    open_notebook_task_norms,
                ),
            )
            for page in pages
        ]

        now_ms = int(time.time() * 1000)
        target_group_id: str | None = None
        seen_keys: set[tuple[str, str, str]] = set()
        handled_keys: set[tuple[str, str, str]] = set()
        batch_upserts: dict[tuple[str, str, str], RapidLogEntryDO] = {}

        # Pass 1: Reconcile existing per-page rows whose content_hash changed
        for page, page_date_ms, entries in parsed_pages:
            for entry in entries:
                key = (page.page_id, entry.kind.value, entry.normalized_text)
                seen_keys.add(key)

                row = entry_map.get(key)
                if row is None:
                    continue

                current_hash = _compute_entry_hash(
                    entry, page.page_index, page_date_ms, file_path
                )
                if row.content_hash == current_hash:
                    handled_keys.add(key)
                    continue

                if entry.kind != RapidLogKind.TASK or entry.task_state is None:
                    updated = _build_entry_row(
                        existing=row,
                        user_id=user_id,
                        file_id=file_id,
                        page_id=page.page_id,
                        page_index=page.page_index,
                        entry=entry,
                        page_date_ms=page_date_ms,
                        content_hash=current_hash,
                        schedule_task_id=None,
                        now_ms=now_ms,
                    )
                    batch_upserts[key] = updated
                    handled_keys.add(key)
                    continue

                if row.schedule_task_id is None:
                    if (
                        row.task_state
                        in (
                            RapidLogTaskState.COMPLETED.value,
                            RapidLogTaskState.CANCELLED.value,
                        )
                        and entry.task_state in _OPEN_TASK_STATES
                    ):
                        continue
                    updated = _build_entry_row(
                        existing=row,
                        user_id=user_id,
                        file_id=file_id,
                        page_id=page.page_id,
                        page_index=page.page_index,
                        entry=entry,
                        page_date_ms=page_date_ms,
                        content_hash=current_hash,
                        schedule_task_id=None,
                        now_ms=now_ms,
                    )
                    batch_upserts[key] = updated
                    handled_keys.add(key)
                    continue

                handled_keys.add(key)
                owned_id: str | None = row.schedule_task_id
                remote = await self.schedule_service.get_task(user_id, owned_id)
                if remote is None:
                    owned_id = None
                elif entry.task_state == RapidLogTaskState.CANCELLED:
                    if remote.status == "needsAction":
                        await self.schedule_service.delete_task(user_id, remote.task_id)
                    owned_id = None
                else:
                    updates = _compute_in_place_task_updates(
                        row=row,
                        entry=entry,
                        remote=remote,
                        file_path=file_path,
                        file_id=file_id,
                        page=page,
                        page_date_ms=page_date_ms,
                        now_ms=now_ms,
                    )
                    if updates:
                        await self.schedule_service.update_task(
                            user_id, remote.task_id, **updates
                        )

                updated = _build_entry_row(
                    existing=row,
                    user_id=user_id,
                    file_id=file_id,
                    page_id=page.page_id,
                    page_index=page.page_index,
                    entry=entry,
                    page_date_ms=page_date_ms,
                    content_hash=current_hash,
                    schedule_task_id=owned_id,
                    now_ms=now_ms,
                )
                batch_upserts.pop(key, None)
                rows_p1 = [updated]
                await self._persist_rows(session_manager, rows_p1)
                entry_map[key] = rows_p1[0]

        # Pre-index unhandled TASK appearances by normalized_text across pages so
        # multi-page chains synced together resolve once on the final page without
        # creating/deleting transient intermediate ScheduleTaskDOs.
        unhandled_tasks_by_norm: dict[
            str, list[tuple[NotePageContentDO, int | None, _ExtractedEntry]]
        ] = {}
        for page, page_date_ms, entries in parsed_pages:
            for entry in entries:
                key = (page.page_id, entry.kind.value, entry.normalized_text)
                if key in handled_keys or entry.kind != RapidLogKind.TASK:
                    continue
                unhandled_tasks_by_norm.setdefault(entry.normalized_text, []).append(
                    (page, page_date_ms, entry)
                )

        carried_detail_by_key: dict[tuple[str, str, str], str] = {}
        carried_star_keys: set[tuple[str, str, str]] = set()
        prior_open_keys: set[tuple[str, str, str]] = set()
        superseded_same_run_keys: set[tuple[str, str, str]] = set()

        for occurrences in unhandled_tasks_by_norm.values():
            if len(occurrences) <= 1:
                continue
            running_detail: str | None = None
            running_star = False
            saw_open = False
            for page, _, entry in occurrences[:-1]:
                k = (page.page_id, entry.kind.value, entry.normalized_text)
                superseded_same_run_keys.add(k)
                if entry.detail:
                    running_detail = entry.detail
                if entry.is_starred:
                    running_star = True
                if entry.task_state in _OPEN_TASK_STATES:
                    saw_open = True

            final_page, _, final_entry = occurrences[-1]
            final_key = (
                final_page.page_id,
                final_entry.kind.value,
                final_entry.normalized_text,
            )
            if final_entry.detail is None and running_detail is not None:
                carried_detail_by_key[final_key] = running_detail
            if not final_entry.is_starred and running_star:
                carried_star_keys.add(final_key)
            if saw_open:
                prior_open_keys.add(final_key)

        # Pass 2: New page appearances & cross-page TASK migrations
        for page, page_date_ms, entries in parsed_pages:
            for entry in entries:
                key = (page.page_id, entry.kind.value, entry.normalized_text)
                if key in handled_keys:
                    continue

                current_hash = _compute_entry_hash(
                    entry, page.page_index, page_date_ms, file_path
                )
                existing_row = entry_map.get(key)

                if (
                    entry.kind != RapidLogKind.TASK
                    or entry.task_state is None
                    or key in superseded_same_run_keys
                ):
                    saved = _build_entry_row(
                        existing=existing_row,
                        user_id=user_id,
                        file_id=file_id,
                        page_id=page.page_id,
                        page_index=page.page_index,
                        entry=entry,
                        page_date_ms=page_date_ms,
                        content_hash=current_hash,
                        schedule_task_id=None,
                        now_ms=now_ms,
                    )
                    batch_upserts[key] = saved
                    entry_map[key] = saved
                    continue

                effective_detail = (
                    entry.detail
                    if entry.detail is not None
                    else carried_detail_by_key.get(key)
                )
                effective_starred = entry.is_starred or (key in carried_star_keys)
                sched_title, sched_detail = _format_schedule_fields(
                    entry.text, effective_detail
                )

                candidates = [
                    c
                    for c in entry_map.values()
                    if c.kind == RapidLogKind.TASK.value
                    and c.normalized_text == entry.normalized_text
                    and c.page_id != page.page_id
                    and c.schedule_task_id is not None
                ]
                candidates.sort(
                    key=lambda c: (
                        0 if c.task_state in _MIGRATED_TASK_VALUES else 1,
                        c.page_index,
                    )
                )

                claimed_candidate: RapidLogEntryDO | None = None
                claimed_remote = None
                superseded_by_later_page = False

                for candidate in candidates:
                    assert candidate.schedule_task_id is not None
                    remote = await self.schedule_service.get_task(
                        user_id, candidate.schedule_task_id
                    )
                    if remote is None:
                        candidate.schedule_task_id = None
                        candidate.update_time = now_ms
                        cand_key = (
                            candidate.page_id,
                            candidate.kind,
                            candidate.normalized_text,
                        )
                        batch_upserts[cand_key] = candidate
                        continue

                    # Prevent backwards ownership theft from a later active page unless
                    # the later page explicitly marked the task migrated (`>`/`<`) to an
                    # active/completed entry on this page.
                    if candidate.page_index > page.page_index:
                        if (
                            candidate.task_state in _MIGRATED_TASK_VALUES
                            and entry.task_state not in _MIGRATED_TASK_VALUES
                        ):
                            claimed_candidate = candidate
                            claimed_remote = remote
                            break
                        if remote.status == "needsAction":
                            superseded_by_later_page = True
                            break
                        continue

                    if (
                        candidate.task_state in _MIGRATED_TASK_VALUES
                        or remote.status == "needsAction"
                    ):
                        claimed_candidate = candidate
                        claimed_remote = remote
                        break

                owned_task_id: str | None = None
                touched_schedule = False
                rows_to_checkpoint: list[RapidLogEntryDO] = []

                if claimed_candidate is not None and claimed_remote is not None:
                    touched_schedule = True
                    claimed_candidate.schedule_task_id = None
                    claimed_candidate.update_time = now_ms
                    cand_key = (
                        claimed_candidate.page_id,
                        claimed_candidate.kind,
                        claimed_candidate.normalized_text,
                    )
                    batch_upserts.pop(cand_key, None)
                    rows_to_checkpoint.append(claimed_candidate)

                    if entry.task_state == RapidLogTaskState.CANCELLED:
                        if claimed_remote.status == "needsAction":
                            await self.schedule_service.delete_task(
                                user_id, claimed_remote.task_id
                            )
                    else:
                        mig_updates: dict[str, Any] = {
                            "title": sched_title,
                            "links": _build_link_b64(
                                file_path, file_id, page, sched_title
                            ),
                        }
                        if effective_detail is not None and sched_detail != (
                            claimed_remote.detail or ""
                        ):
                            mig_updates["detail"] = sched_detail
                        if effective_starred and claimed_remote.importance != "high":
                            mig_updates["importance"] = "high"
                        if (
                            page_date_ms is not None
                            and page_date_ms != claimed_remote.due_time
                        ):
                            mig_updates["due_time"] = page_date_ms
                        if (
                            entry.task_state == RapidLogTaskState.COMPLETED
                            and claimed_remote.status != "completed"
                        ):
                            mig_updates["status"] = "completed"
                            mig_updates["completed_time"] = now_ms

                        await self.schedule_service.update_task(
                            user_id, claimed_remote.task_id, **mig_updates
                        )
                        owned_task_id = claimed_remote.task_id
                elif not superseded_by_later_page and (
                    entry.task_state in _OPEN_TASK_STATES
                    or (
                        entry.task_state == RapidLogTaskState.COMPLETED
                        and key in prior_open_keys
                    )
                ):
                    touched_schedule = True
                    if target_group_id is None:
                        target_group_id = await self._get_or_create_target_group_id(
                            user_id
                        )
                    is_done = entry.task_state == RapidLogTaskState.COMPLETED
                    created = await self.schedule_service.create_task(
                        user_id=user_id,
                        group_id=target_group_id,
                        title=sched_title,
                        detail=sched_detail,
                        status="completed" if is_done else "needsAction",
                        importance="high" if effective_starred else None,
                        due_time=page_date_ms,
                        completed_time_ms=now_ms if is_done else None,
                        links=_build_link_b64(file_path, file_id, page, sched_title),
                    )
                    owned_task_id = created.task_id

                saved_row = _build_entry_row(
                    existing=existing_row,
                    user_id=user_id,
                    file_id=file_id,
                    page_id=page.page_id,
                    page_index=page.page_index,
                    entry=entry,
                    page_date_ms=page_date_ms,
                    content_hash=current_hash,
                    schedule_task_id=owned_task_id,
                    now_ms=now_ms,
                )
                if touched_schedule:
                    batch_upserts.pop(key, None)
                    rows_to_checkpoint.append(saved_row)
                    await self._persist_rows(session_manager, rows_to_checkpoint)
                    saved_row = rows_to_checkpoint[-1]
                else:
                    batch_upserts[key] = saved_row
                entry_map[key] = saved_row

        # Pass 3: Clean up erased lines and deleted pages
        batch_deletes: list[RapidLogEntryDO] = []
        for key, row in list(entry_map.items()):
            if key in seen_keys:
                continue
            batch_upserts.pop(key, None)
            if row.schedule_task_id is not None:
                remote = await self.schedule_service.get_task(
                    user_id, row.schedule_task_id
                )
                if remote is not None and remote.status == "needsAction":
                    await self.schedule_service.delete_task(user_id, remote.task_id)
                await self._persist_rows(
                    session_manager, rows_to_merge=[], rows_to_delete=[row]
                )
            else:
                batch_deletes.append(row)

        await self._persist_rows(
            session_manager,
            rows_to_merge=list(batch_upserts.values()),
            rows_to_delete=batch_deletes,
        )
