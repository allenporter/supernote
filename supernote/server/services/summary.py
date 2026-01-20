import logging
import uuid

from sqlalchemy import and_, select
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
from supernote.server.db.models.summary import SummaryDO, SummaryTagDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import SummaryNotFound
from supernote.server.services.user import UserService

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
        last_modified_time=do.last_modified_time,
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
        creation_time=do.creation_time,
        last_modified_time=do.last_modified_time,
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
    ) -> None:
        """Initialize the summary service."""
        self.user_service = user_service
        self.session_manager = session_manager

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
                md5_hash=dto.md5_hash,
                extra_metadata=dto.metadata,
                comment_str=dto.comment_str,
                comment_handwrite_name=dto.comment_handwrite_name,
                handwrite_inner_name=dto.handwrite_inner_name,
                handwrite_md5=dto.handwrite_md5,
                creation_time=dto.creation_time,
                last_modified_time=dto.last_modified_time,
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

            if dto.content is not None:
                summary_do.content = dto.content
            if dto.tags is not None:
                summary_do.tags = dto.tags
            if dto.metadata is not None:
                summary_do.extra_metadata = dto.metadata
            if dto.last_modified_time is not None:
                summary_do.last_modified_time = dto.last_modified_time
            if dto.md5_hash is not None:
                summary_do.md5_hash = dto.md5_hash

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

    async def list_summaries(
        self,
        user_email: str,
        parent_uuid: str | None = None,
        ids: list[int] | None = None,
        page: int = 1,
        size: int = 20,
    ) -> list[SummaryItem]:
        """List summaries based on filters."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            filters = [
                SummaryDO.user_id == user_id,
                SummaryDO.is_deleted.is_(False),
                SummaryDO.is_summary_group.is_(False),
            ]

            if parent_uuid is not None:
                filters.append(SummaryDO.parent_unique_identifier == parent_uuid)

            if ids:
                filters.append(SummaryDO.id.in_(ids))

            stmt = (
                select(SummaryDO)
                .where(and_(*filters))
                .offset((page - 1) * size)
                .limit(size)
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
                unique_identifier=dto.unique_identifier,
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
            if dto.last_modified_time is not None:
                group_do.last_modified_time = dto.last_modified_time

            await session.commit()
            return True

    async def delete_group(self, user_email: str, group_id: int) -> bool:
        """Delete a summary group (soft delete)."""
        # Note: In a real implementation, we might want to check if the group is empty
        # or recursively delete children. For now, we follow the leaf summary pattern.
        return await self.delete_summary(user_email, group_id)

    async def list_groups(
        self, user_email: str, dto: QuerySummaryGroupDTO
    ) -> list[SummaryItem]:
        """List summary groups for a user."""
        user_id = await self.user_service.get_user_id(user_email)
        page = dto.page or 1
        size = dto.size or 20
        async with self.session_manager.session() as session:
            stmt = (
                select(SummaryDO)
                .where(
                    SummaryDO.user_id == user_id,
                    SummaryDO.is_deleted.is_(False),
                    SummaryDO.is_summary_group.is_(True),
                )
                .offset((page - 1) * size)
                .limit(size)
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
        page = dto.page or 1
        size = dto.size or 20
        async with self.session_manager.session() as session:
            filters = [
                SummaryDO.user_id == user_id,
                SummaryDO.is_deleted.is_(False),
                SummaryDO.is_summary_group.is_(False),
            ]

            if dto.parent_unique_identifier is not None:
                filters.append(
                    SummaryDO.parent_unique_identifier == dto.parent_unique_identifier
                )

            if dto.ids:
                filters.append(SummaryDO.id.in_(dto.ids))

            stmt = (
                select(SummaryDO)
                .where(and_(*filters))
                .offset((page - 1) * size)
                .limit(size)
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
            page=dto.page or 1,
            size=dto.size or 20,
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
