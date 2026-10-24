import hashlib
import logging
import time
import uuid
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.base import BooleanEnum
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
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.summary import SummaryDO, SummaryTagDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import SummaryNotFound
from supernote.server.services.blob import BlobStorage
from supernote.server.services.user import UserService

logger = logging.getLogger(__name__)

DEFAULT_SUMMARY_PAGE_SIZE = 20


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


class SummaryService:
    """Service for managing Summaries, Groups, and Tags."""

    def __init__(
        self,
        user_service: UserService,
        session_manager: DatabaseSessionManager,
        blob_storage: BlobStorage | None = None,
    ) -> None:
        """Initialize the summary service."""
        self.user_service = user_service
        self.session_manager = session_manager
        self.blob_storage = blob_storage

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
            return _to_tag_item(tag_do)

    async def update_tag(self, user_email: str, tag_id: int, name: str) -> bool:
        """Update an existing summary tag."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            tag_do = await self._get_tag(session, user_id, tag_id)
            if not tag_do:
                raise SummaryNotFound(f"Tag with ID {tag_id} not found")
            tag_do.name = name
            await session.commit()
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
        """Add a new summary."""
        user_id = await self.user_service.get_user_id(user_email)
        md5 = dto.md5_hash
        if not md5 and dto.content:
            md5 = hashlib.md5(dto.content.encode("utf-8")).hexdigest()

        now_ms = int(time.time() * 1000)
        creation_time = dto.creation_time or now_ms
        last_modified_time = dto.last_modified_time or now_ms

        async with self.session_manager.session() as session:
            summary_do = SummaryDO(
                user_id=user_id,
                file_id=dto.file_id,
                unique_identifier=dto.unique_identifier or str(uuid.uuid4()),
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
            return _to_summary_item(summary_do)

    async def update_summary(self, user_email: str, dto: UpdateSummaryDTO) -> bool:
        """Update an existing summary."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            summary_do = await self._get_summary(session, user_id, dto.id)
            if not summary_do:
                raise SummaryNotFound(f"Summary with ID {dto.id} not found")

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
            if dto.last_modified_time is not None:
                summary_do.last_modified_time = dto.last_modified_time
            if dto.md5_hash is not None:
                summary_do.md5_hash = dto.md5_hash
            if dto.author is not None:
                summary_do.author = dto.author

            await session.commit()
            return True

    async def delete_summary(self, user_email: str, summary_id: int) -> bool:
        """Soft delete a summary."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            summary_do = await self._get_summary(session, user_id, summary_id)
            if not summary_do:
                raise SummaryNotFound(f"Summary with ID {summary_id} not found")
            summary_do.is_deleted = True
            await session.commit()
            return True

    @staticmethod
    def _build_summary_filters(
        user_id: int,
        parent_uuid: str | None = None,
        ids: list[int] | None = None,
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
    ) -> int:
        """Count total matching summaries for pagination metadata."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            filters = self._build_summary_filters(
                user_id, parent_uuid=parent_uuid, ids=ids
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
    ) -> list[SummaryItem]:
        """List summaries based on filters."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            filters = self._build_summary_filters(
                user_id, parent_uuid=parent_uuid, ids=ids
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
        """Add a new summary group."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            summary_do = SummaryDO(
                user_id=user_id,
                unique_identifier=dto.unique_identifier or str(uuid.uuid4()),
                name=dto.name,
                md5_hash=dto.md5_hash,
                description=dto.description,
                creation_time=dto.creation_time,
                last_modified_time=dto.last_modified_time,
                is_summary_group=True,
            )
            session.add(summary_do)
            await session.commit()
            await session.refresh(summary_do)
            return _to_summary_item(summary_do)

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
            if dto.last_modified_time is not None:
                group_do.last_modified_time = dto.last_modified_time

            await session.commit()
            return True

    async def delete_group(self, user_email: str, group_id: int) -> bool:
        """Delete a summary group (soft delete)."""
        # Note: In a real implementation, we might want to check if the group is empty
        # or recursively delete children. For now, we follow the leaf summary pattern.
        return await self.delete_summary(user_email, group_id)

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

    async def _get_summary_by_uuid(
        self, session: AsyncSession, user_id: int, uuid_str: str | None
    ) -> SummaryDO | None:
        """Helper to get a summary by UUID and user ownership."""
        if not uuid_str:
            return None
        stmt = select(SummaryDO).where(
            SummaryDO.unique_identifier == uuid_str, SummaryDO.user_id == user_id
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_summary_by_uuid(
        self, user_email: str, unique_identifier: str
    ) -> SummaryItem | None:
        """Get a single summary by UUID and user ownership."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            summary_do = await self._get_summary_by_uuid(
                session, user_id, unique_identifier
            )
            if not summary_do:
                return None
            return _to_summary_item(summary_do)

    async def get_summary(self, user_email: str, summary_id: int) -> SummaryItem:
        """Get a single summary by ID."""
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
        """Helper to get a summary by ID and user ownership."""
        stmt = select(SummaryDO).where(
            SummaryDO.id == summary_id, SummaryDO.user_id == user_id
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
        async with self.session_manager.session() as session:
            stmt = select(SummaryDO).where(
                SummaryDO.user_id == user_id,
                SummaryDO.file_id == file_id,
                SummaryDO.is_deleted.is_(False),
            )
            result = await session.execute(stmt)
            summaries = list(result.scalars().all())
            return [_to_summary_item(s) for s in summaries]

    async def delete_user_data(self, user_id: int) -> None:
        """Permanently delete all summaries, summary tags, and unreferenced handwriting blobs for a user.

        Deletes physical handwriting blobs in `USER_DATA_BUCKET` before deleting database
        metadata rows so interrupted runs remain idempotent and never orphan blobs.

        WARNING: This permanently deletes all SummaryDO and SummaryTagDO records for
        `user_id` and removes any referenced handwriting blobs in `USER_DATA_BUCKET`
        that are not referenced by any other user's summary or file.
        """
        blobs_to_delete: set[str] = set()
        if self.blob_storage is not None:
            async with self.session_manager.session() as session:
                hw_stmt = select(SummaryDO.handwrite_inner_name).where(
                    SummaryDO.user_id == user_id,
                    SummaryDO.handwrite_inner_name.is_not(None),
                )
                candidate_keys = {
                    k for k in (await session.execute(hw_stmt)).scalars().all() if k
                }
                if candidate_keys:
                    surviving_hw = {
                        k
                        for k in (
                            await session.execute(
                                select(SummaryDO.handwrite_inner_name)
                                .where(
                                    SummaryDO.user_id != user_id,
                                    SummaryDO.handwrite_inner_name.in_(candidate_keys),
                                )
                                .group_by(SummaryDO.handwrite_inner_name)
                            )
                        )
                        .scalars()
                        .all()
                        if k is not None
                    }
                    surviving_files = {
                        k
                        for k in (
                            await session.execute(
                                select(UserFileDO.storage_key)
                                .where(
                                    UserFileDO.user_id != user_id,
                                    UserFileDO.storage_key.in_(candidate_keys),
                                )
                                .group_by(UserFileDO.storage_key)
                            )
                        )
                        .scalars()
                        .all()
                        if k is not None
                    }
                    blobs_to_delete = candidate_keys - surviving_hw - surviving_files

            for blob_key in blobs_to_delete:
                try:
                    await self.blob_storage.delete(USER_DATA_BUCKET, blob_key)
                except (FileNotFoundError, ValueError) as e:
                    logger.warning(
                        f"Skipping invalid or missing summary blob {blob_key}: {e}"
                    )

        async with self.session_manager.session() as session:
            await session.execute(delete(SummaryDO).where(SummaryDO.user_id == user_id))
            await session.execute(
                delete(SummaryTagDO).where(SummaryTagDO.user_id == user_id)
            )
            await session.commit()
