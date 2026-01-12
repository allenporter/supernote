import logging
import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.base import BooleanEnum
from supernote.models.summary import (
    AddSummaryDTO,
    SummaryItem,
    SummaryTagItem,
    UpdateSummaryDTO,
)
from supernote.server.db.models.summary import SummaryDO, SummaryTagDO
from supernote.server.db.session import DatabaseSessionManager
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
                return False
            tag_do.name = name
            await session.commit()
            return True

    async def delete_tag(self, user_email: str, tag_id: int) -> bool:
        """Delete a summary tag."""
        user_id = await self.user_service.get_user_id(user_email)
        async with self.session_manager.session() as session:
            tag_do = await self._get_tag(session, user_id, tag_id)
            if not tag_do:
                return False
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
                return False

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
                return False
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
            filters = [SummaryDO.user_id == user_id, SummaryDO.is_deleted == False]

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
