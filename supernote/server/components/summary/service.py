"""CRUD, group hierarchy, and tag management service for notebook summaries.

`SummaryService` manages `SummaryDO` (both summary groups and individual AI/handwritten
summaries) and `SummaryTagDO` records, enforces soft-delete retention windows
(`purge_expired_summaries`), and emits `SummaryCreatedEvent`, `SummaryUpdatedEvent`, `SummaryDeletedEvent`,
and `BlobCleanupEvent` onto `supernote.server.events.LocalEventBus`. Used by
`supernote.server.components.summary.http` and
`supernote.server.components.summary.processor.SummaryModule`.
See `supernote.guides.summary_api`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import Any

from aiohttp import web
from sqlalchemy import ColumnElement, Select, and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.base import BooleanEnum
from supernote.models.extended import DigestHandwritingVO, DigestListVO, DigestVO
from supernote.models.summary import (
    AddSummaryDTO,
    AddSummaryGroupDTO,
    QuerySummaryDTO,
    QuerySummaryGroupDTO,
    SummaryInfoItem,
    SummaryItem,
    SummaryTagItem,
    UpdateSummaryDTO,
    UpdateSummaryGroupDTO,
)
from supernote.server.components.transcript import TranscriptService
from supernote.server.constants import RECYCLE_RETENTION_MS
from supernote.server.db.models.summary import SummaryDO, SummaryTagDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import (
    BlobCleanupEvent,
    LocalEventBus,
    SummaryCreatedEvent,
    SummaryDeletedEvent,
    SummaryTagDeletedEvent,
    SummaryTagUpsertedEvent,
    SummaryUpdatedEvent,
)
from supernote.server.exceptions import SummaryNotFound
from supernote.server.services.user import UserService

DEFAULT_SUMMARY_PAGE_SIZE = 20
SUMMARY_PURGE_INTERVAL_SECONDS = 300
logger = logging.getLogger(__name__)


def _to_tag_item(do: SummaryTagDO) -> SummaryTagItem:
    """Convert SummaryTagDO to SummaryTagItem."""
    return SummaryTagItem(
        id=do.id,
        name=do.name,
        user_id=do.user_id,
        unique_identifier=do.unique_identifier,
        created_at=do.create_time,
    )


def _to_summary_info_item(do: SummaryDO) -> SummaryInfoItem:
    """Convert SummaryDO to SummaryInfoItem."""
    return SummaryInfoItem(
        id=do.id,
        user_id=do.user_id,
        md5_hash=do.md5_hash,
        handwrite_md5=do.handwrite_md5,
        comment_handwrite_name=do.comment_handwrite_name,
        last_modified_time=do.last_modified_time or do.update_time or do.create_time,
    )


def _to_summary_item(do: SummaryDO) -> SummaryItem:
    """Convert SummaryDO to SummaryItem."""
    return SummaryItem(
        id=do.id,
        file_id=do.file_id,
        name=do.name,
        user_id=do.user_id,
        unique_identifier=do.unique_identifier,
        parent_unique_identifier=do.parent_unique_identifier,
        content=do.content,
        source_path=do.source_path,
        data_source=do.data_source,
        source_type=do.source_type,
        is_summary_group=BooleanEnum.of(bool(do.is_summary_group)),
        description=do.description,
        tags=do.tags,
        md5_hash=do.md5_hash,
        metadata=do.extra_metadata,
        comment_str=do.comment_str,
        comment_handwrite_name=do.comment_handwrite_name,
        handwrite_inner_name=do.handwrite_inner_name,
        handwrite_md5=do.handwrite_md5,
        creation_time=do.creation_time or do.create_time,
        last_modified_time=do.last_modified_time or do.update_time or do.create_time,
        is_deleted=BooleanEnum.of(bool(do.is_deleted)),
        create_time=do.create_time,
        update_time=do.update_time,
        author=do.author,
    )


def _resolve_digest_author(summary: SummaryItem) -> str | None:
    """Return top-level author, falling back to JSON metadata['author']."""
    if summary.author and summary.author.strip():
        return summary.author.strip()
    if not summary.metadata or not summary.metadata.strip():
        return None
    try:
        parsed = json.loads(summary.metadata)
    except ValueError:
        return None
    if isinstance(parsed, dict):
        meta_author = parsed.get("author")
        if isinstance(meta_author, str) and meta_author.strip():
            return meta_author.strip()
    return None


class SummaryService:
    """Service for managing Summaries, Groups, and Tags."""

    def __init__(
        self,
        user_service: UserService,
        session_manager: DatabaseSessionManager,
        event_bus: LocalEventBus | None = None,
        purge_interval_seconds: float = SUMMARY_PURGE_INTERVAL_SECONDS,
    ) -> None:
        """Initialize the summary service."""
        self.user_service = user_service
        self.session_manager = session_manager
        self.event_bus = event_bus
        self._purge_interval_seconds = purge_interval_seconds
        self._purge_task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """Start periodic hard-deletion of expired soft-deleted summaries."""
        if self._purge_task is not None and not self._purge_task.done():
            return
        self._shutdown_event.clear()
        self._purge_task = asyncio.create_task(self._purge_loop())

    async def stop(self) -> None:
        """Stop the periodic summary purge loop idempotently."""
        self._shutdown_event.set()
        if self._purge_task is not None:
            self._purge_task.cancel()
            try:
                await self._purge_task
            except asyncio.CancelledError:
                pass
            self._purge_task = None

    async def _purge_loop(self) -> None:
        """Periodically purge soft-deleted summaries past retention."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(self._purge_interval_seconds)
                await self.purge_expired_summaries()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error purging expired summaries: {e}", exc_info=True)

    async def add_tag(self, user_email: str, name: str) -> SummaryTagItem:
        """Add a new summary tag."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            tag_do = SummaryTagDO(
                user_id=user_id,
                name=name,
                unique_identifier=str(uuid.uuid4()),
            )
            session.add(tag_do)
            await session.commit()
            await session.refresh(tag_do)
            tag_item = _to_tag_item(tag_do)
        if self.event_bus is not None:
            await self.event_bus.publish(
                SummaryTagUpsertedEvent(
                    user_id=user_id,
                    tag=tag_item,
                    is_new=True,
                )
            )
        return tag_item

    async def update_tag(self, user_email: str, tag_id: int, name: str) -> bool:
        """Update an existing summary tag."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            tag_do = await self._get_tag(session, user_id, tag_id)
            if not tag_do:
                raise SummaryNotFound(f"Tag with ID {tag_id} not found")
            tag_do.name = name
            await session.commit()
            await session.refresh(tag_do)
            tag_item = _to_tag_item(tag_do)
        if self.event_bus is not None:
            await self.event_bus.publish(
                SummaryTagUpsertedEvent(
                    user_id=user_id,
                    tag=tag_item,
                    is_new=False,
                )
            )
        return True

    async def delete_tag(self, user_email: str, tag_id: int) -> bool:
        """Delete a summary tag."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            tag_do = await self._get_tag(session, user_id, tag_id)
            if not tag_do:
                raise SummaryNotFound(f"Tag with ID {tag_id} not found")
            await session.delete(tag_do)
            await session.commit()
        if self.event_bus is not None:
            await self.event_bus.publish(
                SummaryTagDeletedEvent(
                    user_id=user_id,
                    tag_id=tag_id,
                )
            )
        return True

    async def list_tags(self, user_email: str) -> list[SummaryTagItem]:
        """List all summary tags for a user."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            stmt = select(SummaryTagDO).where(SummaryTagDO.user_id == user_id)
            result = await session.execute(stmt)
            tags = list(result.scalars().all())
            return [_to_tag_item(tag) for tag in tags]

    async def add_summary(self, user_email: str, dto: AddSummaryDTO) -> SummaryItem:
        """Add a new summary, reviving any existing row with the same unique_identifier."""
        user_id = await self.user_service.get_user_id(user_email)
        md5 = dto.md5_hash
        if not md5 and dto.content:
            md5 = hashlib.md5(dto.content.encode("utf-8")).hexdigest()

        now_ms = int(time.time() * 1000)
        creation_time = dto.creation_time if dto.creation_time is not None else now_ms
        last_modified_time = (
            dto.last_modified_time if dto.last_modified_time is not None else now_ms
        )
        unique_identifier = dto.unique_identifier or str(uuid.uuid4())

        async with self.session_manager.session() as session:
            old_inner_name = await self._replace_existing_by_uuid(
                session, user_id, unique_identifier
            )
            summary_do = SummaryDO(
                user_id=user_id,
                file_id=dto.file_id,
                unique_identifier=unique_identifier,
                parent_unique_identifier=dto.parent_unique_identifier,
                content=dto.content,
                source_path=dto.source_path,
                data_source=dto.data_source,
                source_type=dto.source_type,
                is_summary_group=False,
                tags=dto.tags,
                md5_hash=md5,
                extra_metadata=dto.metadata,
                comment_str=dto.comment_str,
                comment_handwrite_name=dto.comment_handwrite_name,
                handwrite_inner_name=dto.handwrite_inner_name,
                handwrite_md5=dto.handwrite_md5,
                creation_time=creation_time,
                last_modified_time=last_modified_time,
                author=dto.author,
            )
            session.add(summary_do)
            await session.commit()
            await session.refresh(summary_do)
            summary_item = _to_summary_item(summary_do)
        if self.event_bus is not None:
            await self.event_bus.publish(
                SummaryCreatedEvent(
                    user_id=user_id,
                    summary=summary_item,
                )
            )
            if old_inner_name and old_inner_name != dto.handwrite_inner_name:
                await self.event_bus.publish(
                    BlobCleanupEvent(storage_keys={old_inner_name})
                )
        return summary_item

    async def update_summary(self, user_email: str, dto: UpdateSummaryDTO) -> bool:
        """Update an existing summary."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            summary_do = await self._get_summary(session, user_id, dto.id)
            if not summary_do:
                raise SummaryNotFound(f"Summary with ID {dto.id} not found")

            old_inner_name = summary_do.handwrite_inner_name

            if dto.parent_unique_identifier is not None:
                summary_do.parent_unique_identifier = dto.parent_unique_identifier
            if dto.content is not None:
                summary_do.content = dto.content
                if dto.md5_hash is None:
                    summary_do.md5_hash = hashlib.md5(
                        dto.content.encode("utf-8")
                    ).hexdigest()
            if dto.source_path is not None:
                summary_do.source_path = dto.source_path
            if dto.data_source is not None:
                summary_do.data_source = dto.data_source
            if dto.source_type is not None:
                summary_do.source_type = dto.source_type
            if dto.tags is not None:
                summary_do.tags = dto.tags
            if dto.metadata is not None:
                summary_do.extra_metadata = dto.metadata
            if dto.comment_str is not None:
                summary_do.comment_str = dto.comment_str
            if dto.comment_handwrite_name is not None:
                summary_do.comment_handwrite_name = dto.comment_handwrite_name
            if dto.handwrite_inner_name is not None:
                summary_do.handwrite_inner_name = dto.handwrite_inner_name
            if dto.handwrite_md5 is not None:
                summary_do.handwrite_md5 = dto.handwrite_md5
            summary_do.last_modified_time = (
                dto.last_modified_time
                if dto.last_modified_time is not None
                else int(time.time() * 1000)
            )
            if dto.md5_hash is not None:
                summary_do.md5_hash = dto.md5_hash
            if dto.author is not None:
                summary_do.author = dto.author

            new_inner_name = summary_do.handwrite_inner_name
            await session.commit()
            await session.refresh(summary_do)
            summary_item = _to_summary_item(summary_do)

        if self.event_bus is not None:
            await self.event_bus.publish(
                SummaryUpdatedEvent(
                    user_id=user_id,
                    summary=summary_item,
                )
            )
            # When handwrite_inner_name is overwritten in-place on an existing summary,
            # the superseded key is no longer tracked on SummaryDO (unlike soft-delete,
            # which retains the row and blob for RECYCLE_RETENTION_MS).
            if old_inner_name and old_inner_name != new_inner_name:
                await self.event_bus.publish(
                    BlobCleanupEvent(storage_keys={old_inner_name})
                )
        return True

    async def delete_summary(self, user_email: str, summary_id: int) -> bool:
        """Soft delete a summary (retaining its row and blob for RECYCLE_RETENTION_MS before hard purge)."""
        user_id = await self.user_service.get_user_id(user_email)
        deleted_events: list[SummaryDeletedEvent] = []
        async with self.session_manager.session() as session:
            summary_do = await self._get_summary(session, user_id, summary_id)
            if not summary_do:
                raise SummaryNotFound(f"Summary with ID {summary_id} not found")

            is_summary_group = bool(summary_do.is_summary_group)
            summary_do.is_deleted = True
            deleted_events.append(
                SummaryDeletedEvent(
                    user_id=user_id,
                    summary_id=summary_id,
                    is_summary_group=is_summary_group,
                    file_id=summary_do.file_id,
                    unique_identifier=summary_do.unique_identifier,
                )
            )

            if is_summary_group:
                child_stmt = select(SummaryDO).where(
                    SummaryDO.user_id == user_id,
                    SummaryDO.parent_unique_identifier == summary_do.unique_identifier,
                    SummaryDO.is_deleted.is_(False),
                )
                children = list((await session.execute(child_stmt)).scalars().all())
                for child in children:
                    child.is_deleted = True
                    deleted_events.append(
                        SummaryDeletedEvent(
                            user_id=user_id,
                            summary_id=child.id,
                            is_summary_group=False,
                            file_id=child.file_id,
                            unique_identifier=child.unique_identifier,
                        )
                    )

            await session.commit()
        if self.event_bus is not None:
            for ev in deleted_events:
                await self.event_bus.publish(ev)
        return True

    @staticmethod
    def _build_summary_filters(
        user_id: int,
        parent_uuid: str | None = None,
        ids: list[int] | None = None,
        file_id: int | None = None,
    ) -> list[ColumnElement[bool]]:
        """Build SQLAlchemy filter predicates for leaf summaries."""
        filters: list[ColumnElement[bool]] = [
            SummaryDO.user_id == user_id,
            SummaryDO.is_deleted.is_(False),
            SummaryDO.is_summary_group.is_(False),
        ]
        if parent_uuid is not None:
            filters.append(SummaryDO.parent_unique_identifier == parent_uuid)
        if ids is not None:
            filters.append(SummaryDO.id.in_(ids))
        if file_id is not None:
            filters.append(SummaryDO.file_id == file_id)
        return filters

    @staticmethod
    def _apply_pagination[T: Select[Any]](
        stmt: T,
        page: int | None,
        size: int | None,
    ) -> T:
        """Apply SQL offset and limit when a positive page size is specified."""
        if size is not None and size > 0:
            effective_page = max(1, page or 1)
            return stmt.offset((effective_page - 1) * size).limit(size)
        return stmt

    async def count_summaries(
        self,
        user_email: str,
        parent_uuid: str | None = None,
        ids: list[int] | None = None,
        file_id: int | None = None,
    ) -> int:
        """Count total matching summaries for pagination metadata."""
        user_id = await self.user_service.get_user_id(user_email)
        return await self.count_summaries_for_user(
            user_id, parent_uuid=parent_uuid, ids=ids, file_id=file_id
        )

    async def count_summaries_for_user(
        self,
        user_id: int,
        *,
        parent_uuid: str | None = None,
        ids: list[int] | None = None,
        file_id: int | None = None,
    ) -> int:
        """Count matching active leaf summaries for `user_id`."""
        async with self.session_manager.session() as session:
            filters = self._build_summary_filters(
                user_id, parent_uuid=parent_uuid, ids=ids, file_id=file_id
            )
            stmt = select(func.count()).select_from(SummaryDO).where(and_(*filters))
            return int((await session.execute(stmt)).scalar() or 0)

    async def list_summaries(
        self,
        user_email: str,
        parent_uuid: str | None = None,
        ids: list[int] | None = None,
        page: int | None = 1,
        size: int | None = DEFAULT_SUMMARY_PAGE_SIZE,
        file_id: int | None = None,
    ) -> list[SummaryItem]:
        """List summaries based on filters."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            filters = self._build_summary_filters(
                user_id, parent_uuid=parent_uuid, ids=ids, file_id=file_id
            )
            stmt = self._apply_pagination(
                select(SummaryDO).where(and_(*filters)).order_by(SummaryDO.id.asc()),
                page,
                size,
            )
            result = await session.execute(stmt)
            summaries = list(result.scalars().all())
            return [_to_summary_item(s) for s in summaries]

    async def add_group(self, user_email: str, dto: AddSummaryGroupDTO) -> SummaryItem:
        """Add a new summary group, reviving any existing row with the same unique_identifier."""
        user_id = await self.user_service.get_user_id(user_email)
        now_ms = int(time.time() * 1000)
        creation_time = dto.creation_time if dto.creation_time is not None else now_ms
        last_modified_time = (
            dto.last_modified_time if dto.last_modified_time is not None else now_ms
        )
        unique_identifier = dto.unique_identifier or str(uuid.uuid4())

        async with self.session_manager.session() as session:
            old_inner_name = await self._replace_existing_by_uuid(
                session, user_id, unique_identifier
            )
            summary_do = SummaryDO(
                user_id=user_id,
                unique_identifier=unique_identifier,
                name=dto.name,
                md5_hash=dto.md5_hash,
                description=dto.description,
                creation_time=creation_time,
                last_modified_time=last_modified_time,
                is_summary_group=True,
            )
            session.add(summary_do)
            await session.commit()
            await session.refresh(summary_do)
            summary_item = _to_summary_item(summary_do)
        if self.event_bus is not None:
            await self.event_bus.publish(
                SummaryCreatedEvent(
                    user_id=user_id,
                    summary=summary_item,
                )
            )
            if old_inner_name:
                await self.event_bus.publish(
                    BlobCleanupEvent(storage_keys={old_inner_name})
                )
        return summary_item

    async def update_group(self, user_email: str, dto: UpdateSummaryGroupDTO) -> bool:
        """Update an existing summary group."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            group_do = await self._get_summary_by_uuid(
                session, user_id, dto.unique_identifier
            )
            if not group_do or not group_do.is_summary_group:
                # If not found by UUID, try by ID if available (though UUID is preferred for sync)
                group_do = await self._get_summary(session, user_id, dto.id)
                if not group_do or not group_do.is_summary_group:
                    raise SummaryNotFound(f"Group with ID {dto.id} not found")

            old_inner_name = group_do.handwrite_inner_name

            group_do.md5_hash = dto.md5_hash
            if dto.name is not None:
                group_do.name = dto.name
            if dto.description is not None:
                group_do.description = dto.description
            if dto.metadata is not None:
                group_do.extra_metadata = dto.metadata
            if dto.comment_str is not None:
                group_do.comment_str = dto.comment_str
            if dto.comment_handwrite_name is not None:
                group_do.comment_handwrite_name = dto.comment_handwrite_name
            if dto.handwrite_inner_name is not None:
                group_do.handwrite_inner_name = dto.handwrite_inner_name
            group_do.last_modified_time = (
                dto.last_modified_time
                if dto.last_modified_time is not None
                else int(time.time() * 1000)
            )

            new_inner_name = group_do.handwrite_inner_name
            await session.commit()
            await session.refresh(group_do)
            summary_item = _to_summary_item(group_do)

        if self.event_bus is not None:
            await self.event_bus.publish(
                SummaryUpdatedEvent(
                    user_id=user_id,
                    summary=summary_item,
                )
            )
            # Overwriting handwrite_inner_name in-place supersedes the previous key;
            # soft-deleted groups instead retain their blob for RECYCLE_RETENTION_MS.
            if old_inner_name and old_inner_name != new_inner_name:
                await self.event_bus.publish(
                    BlobCleanupEvent(storage_keys={old_inner_name})
                )
        return True

    async def delete_group(self, user_email: str, group_id: int) -> bool:
        """Delete a summary group and its child summaries (soft delete)."""
        return await self.delete_summary(user_email, group_id)

    async def purge_expired_summaries(self, older_than_ms: int | None = None) -> int:
        """Hard-delete soft-deleted summaries older than the retention window and publish blob cleanup events."""
        cutoff_ms = (
            older_than_ms
            if older_than_ms is not None
            else int(time.time() * 1000) - RECYCLE_RETENTION_MS
        )
        async with self.session_manager.session() as session:
            stmt = select(SummaryDO.id, SummaryDO.handwrite_inner_name).where(
                SummaryDO.is_deleted.is_(True),
                SummaryDO.update_time <= cutoff_ms,
            )
            rows = (await session.execute(stmt)).all()
            if not rows:
                return 0

            expired_ids = [row_id for row_id, _ in rows]
            candidate_keys = {
                inner_name for _, inner_name in rows if inner_name is not None
            }
            await session.execute(
                delete(SummaryDO).where(SummaryDO.id.in_(expired_ids))
            )
            await session.commit()

        if self.event_bus and candidate_keys:
            await self.event_bus.publish(BlobCleanupEvent(storage_keys=candidate_keys))
        return len(expired_ids)

    async def count_groups(self, user_email: str) -> int:
        """Count total non-deleted summary groups for a user."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            stmt = (
                select(func.count())
                .select_from(SummaryDO)
                .where(
                    SummaryDO.user_id == user_id,
                    SummaryDO.is_deleted.is_(False),
                    SummaryDO.is_summary_group.is_(True),
                )
            )
            return int((await session.execute(stmt)).scalar() or 0)

    async def list_groups(
        self, user_email: str, dto: QuerySummaryGroupDTO
    ) -> list[SummaryItem]:
        """List summary groups for a user."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            stmt = self._apply_pagination(
                select(SummaryDO)
                .where(
                    SummaryDO.user_id == user_id,
                    SummaryDO.is_deleted.is_(False),
                    SummaryDO.is_summary_group.is_(True),
                )
                .order_by(SummaryDO.id.asc()),
                dto.page,
                dto.size,
            )
            result = await session.execute(stmt)
            groups = list(result.scalars().all())
            return [_to_summary_item(g) for g in groups]

    async def _replace_existing_by_uuid(
        self, session: AsyncSession, user_id: int, unique_identifier: str
    ) -> str | None:
        """Remove any existing row with the same UUID (including soft-deleted) and return its handwriting key."""
        existing_do = await self._get_summary_by_uuid(
            session, user_id, unique_identifier, include_deleted=True
        )
        if existing_do is None:
            return None
        old_inner_name = existing_do.handwrite_inner_name
        await session.delete(existing_do)
        await session.flush()
        return old_inner_name

    async def _get_summary_by_uuid(
        self,
        session: AsyncSession,
        user_id: int,
        uuid_str: str | None,
        include_deleted: bool = False,
    ) -> SummaryDO | None:
        """Helper to get a summary by UUID and user ownership."""
        if not uuid_str:
            return None
        stmt = select(SummaryDO).where(
            SummaryDO.unique_identifier == uuid_str, SummaryDO.user_id == user_id
        )
        if not include_deleted:
            stmt = stmt.where(SummaryDO.is_deleted.is_(False))
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_summary_by_uuid(
        self, user_email: str, unique_identifier: str
    ) -> SummaryItem | None:
        """Get a single active summary by UUID and user ownership."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            summary_do = await self._get_summary_by_uuid(
                session, user_id, unique_identifier
            )
            if not summary_do:
                return None
            return _to_summary_item(summary_do)

    async def get_summary(self, user_email: str, summary_id: int) -> SummaryItem:
        """Get a single active summary by ID."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            summary_do = await self._get_summary(session, user_id, summary_id)
            if not summary_do:
                raise SummaryNotFound(f"Summary with ID {summary_id} not found")
            return _to_summary_item(summary_do)

    async def list_summary_infos(
        self, user_email: str, dto: QuerySummaryDTO
    ) -> list[SummaryInfoItem]:
        """List lightweight summary info for integrity checking."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            filters = self._build_summary_filters(
                user_id,
                parent_uuid=dto.parent_unique_identifier,
                ids=dto.ids,
            )
            stmt = self._apply_pagination(
                select(SummaryDO).where(and_(*filters)).order_by(SummaryDO.id.asc()),
                dto.page,
                dto.size,
            )
            result = await session.execute(stmt)
            summaries = list(result.scalars().all())
            return [_to_summary_info_item(s) for s in summaries]

    async def list_summaries_by_id(
        self, user_email: str, dto: QuerySummaryDTO
    ) -> list[SummaryItem]:
        """List full summaries by IDs."""
        return await self.list_summaries(
            user_email,
            parent_uuid=dto.parent_unique_identifier,
            ids=dto.ids,
            page=dto.page,
            size=dto.size,
        )

    async def _get_summary(
        self, session: AsyncSession, user_id: int, summary_id: int
    ) -> SummaryDO | None:
        """Helper to get an active summary by ID and user ownership."""
        stmt = select(SummaryDO).where(
            SummaryDO.id == summary_id,
            SummaryDO.user_id == user_id,
            SummaryDO.is_deleted.is_(False),
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_tag(
        self, session: AsyncSession, user_id: int, tag_id: int
    ) -> SummaryTagDO | None:
        """Helper to get a tag by ID and user ownership."""
        stmt = select(SummaryTagDO).where(
            SummaryTagDO.id == tag_id, SummaryTagDO.user_id == user_id
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_summaries_for_file_internal(
        self, user_email: str, file_id: int
    ) -> list[SummaryItem]:
        """Internal helper to list summaries for a specific file.

        This is NOT part of the standard public API but used by web frontend extensions.
        """
        user_id = await self.user_service.get_user_id(user_email)
        return await self.list_summaries_for_user(user_id, file_id=file_id)

    async def list_summaries_for_user(
        self,
        user_id: int,
        *,
        file_id: int | None = None,
        parent_uuid: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SummaryItem]:
        """List active leaf summaries for `user_id`, optionally filtered by `file_id` or category."""
        async with self.session_manager.session() as session:
            filters = self._build_summary_filters(
                user_id, parent_uuid=parent_uuid, file_id=file_id
            )
            stmt = (
                select(SummaryDO)
                .where(and_(*filters))
                .order_by(SummaryDO.update_time.desc(), SummaryDO.id.desc())
            )
            if offset > 0:
                stmt = stmt.offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            summaries = list(result.scalars().all())
            return [_to_summary_item(s) for s in summaries]

    async def list_digests(
        self,
        user_id: int,
        transcript_service: TranscriptService,
        *,
        file_id: int | None = None,
        category_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> DigestListVO:
        """List self-contained `DigestVO` items with inline handwriting OCR transcripts."""
        clamped_limit = max(1, min(limit, 200))
        clamped_offset = max(0, offset)
        summaries = await self.list_summaries_for_user(
            user_id,
            file_id=file_id,
            parent_uuid=category_id,
            limit=clamped_limit,
            offset=clamped_offset,
        )
        total = await self.count_summaries_for_user(
            user_id,
            file_id=file_id,
            parent_uuid=category_id,
        )
        summary_ids = [s.id for s in summaries if s.id is not None]
        transcripts = await transcript_service.get_summary_transcripts(
            user_id, summary_ids
        )

        items: list[DigestVO] = []
        for summary in summaries:
            if summary.id is None:
                continue
            handwriting: DigestHandwritingVO | None = None
            if summary.handwrite_inner_name:
                transcript = transcripts.get(summary.id)
                is_current = (
                    transcript is not None
                    and bool(summary.handwrite_md5)
                    and transcript.handwrite_md5 == summary.handwrite_md5
                )
                handwriting = DigestHandwritingVO(
                    md5=summary.handwrite_md5,
                    transcript=transcript.text if is_current and transcript else None,
                    model_id=transcript.model_id if is_current and transcript else None,
                    update_time=(
                        transcript.update_time if is_current and transcript else None
                    ),
                )
            tags = (
                [t.strip() for t in summary.tags.split(",") if t.strip()]
                if summary.tags
                else []
            )
            items.append(
                DigestVO(
                    id=summary.id,
                    unique_identifier=summary.unique_identifier,
                    category_id=summary.parent_unique_identifier,
                    file_id=summary.file_id,
                    name=summary.name,
                    source_path=summary.source_path,
                    author=_resolve_digest_author(summary),
                    tags=tags,
                    data_source=summary.data_source,
                    content=summary.content,
                    comment=summary.comment_str,
                    handwriting=handwriting,
                    creation_time=summary.creation_time,
                    update_time=summary.last_modified_time or summary.update_time,
                )
            )

        return DigestListVO(
            digests=items,
            total=total,
            limit=clamped_limit,
            offset=clamped_offset,
        )

    @staticmethod
    async def get_referenced_blob_keys(
        session: AsyncSession, candidate_keys: set[str]
    ) -> set[str]:
        """Return the subset of ``candidate_keys`` still referenced by `SummaryDO` handwriting blobs.

        Intentionally queries across all users (matching `VirtualFileSystem.get_unreferenced_storage_keys`):
        `USER_DATA_BUCKET` is a shared blob store, so deletion safety must confirm no user still
        references a physical key before `FileService.cleanup_unreferenced_blobs` deletes it.
        """
        if not candidate_keys:
            return set()
        stmt = (
            select(SummaryDO.handwrite_inner_name)
            .where(SummaryDO.handwrite_inner_name.in_(candidate_keys))
            .group_by(SummaryDO.handwrite_inner_name)
        )
        return {k for k in (await session.execute(stmt)).scalars().all() if k}


SUMMARY_SERVICE_KEY: web.AppKey[SummaryService] = web.AppKey("summary_service")
"""Typed `aiohttp.web.AppKey` exposing `SummaryService` to sibling components and routes."""
