import logging
import time
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.file import RecycleFileDO, UserFileDO

logger = logging.getLogger(__name__)


class VirtualFileSystem:
    """
    Core implementation of the Database-Driven Virtual Filesystem.
    """

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def create_directory(
        self, user_id: int, parent_id: int, name: str
    ) -> UserFileDO:
        """Create a new directory."""
        # Check if already exists
        stmt = select(UserFileDO).where(
            UserFileDO.user_id == user_id,
            UserFileDO.directory_id == parent_id,
            UserFileDO.file_name == name,
            UserFileDO.is_active == "Y",
            UserFileDO.is_folder == "Y",
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return existing  # Or raise error?

        now = int(time.time() * 1000)  # ms
        new_dir = UserFileDO(
            user_id=user_id,
            directory_id=parent_id,
            file_name=name,
            is_folder="Y",
            size=0,
            create_time=now,
            update_time=now,
            is_active="Y",
        )
        self.db.add(new_dir)
        await self.db.commit()
        await self.db.refresh(new_dir)
        return new_dir

    async def list_directory(self, user_id: int, parent_id: int) -> List[UserFileDO]:
        """List active files/folders in a directory."""
        stmt = select(UserFileDO).where(
            UserFileDO.user_id == user_id,
            UserFileDO.directory_id == parent_id,
            UserFileDO.is_active == "Y",
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create_file(
        self, user_id: int, parent_id: int, name: str, size: int, md5: str
    ) -> UserFileDO:
        """Create a file entry (assuming content is handled elsewhere/CAS)."""
        now = int(time.time() * 1000)

        # Check quota (TODO: Implement Capacity check)

        new_file = UserFileDO(
            user_id=user_id,
            directory_id=parent_id,
            file_name=name,
            is_folder="N",
            size=size,
            md5=md5,
            create_time=now,
            update_time=now,
            is_active="Y",
        )
        self.db.add(new_file)
        await self.db.commit()
        await self.db.refresh(new_file)
        return new_file

    async def get_node_by_id(self, user_id: int, node_id: int) -> Optional[UserFileDO]:
        stmt = select(UserFileDO).where(
            UserFileDO.user_id == user_id,
            UserFileDO.id == node_id,
            UserFileDO.is_active == "Y",
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_node(self, user_id: int, node_id: int) -> bool:
        """Soft delete a file/folder."""
        node = await self.get_node_by_id(user_id, node_id)
        if not node:
            return False

        # TODO: Handle recursive soft delete for folders?
        # For now, just mark the node.

        node.is_active = "N"

        # Create recycle bin entry
        recycle = RecycleFileDO(
            user_id=user_id,
            file_id=node.id,
            file_name=node.file_name,
            size=node.size,
            is_folder=node.is_folder,
            delete_time=int(time.time() * 1000),
        )
        self.db.add(recycle)

        await self.db.commit()
        return True
