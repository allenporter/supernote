import logging
import time
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.file import RecycleFileDO, UserFileDO
from supernote.server.exceptions import FileAlreadyExists, InvalidPath

logger = logging.getLogger(__name__)


class VirtualFileSystem:
    """Core implementation of the Database-Driven Virtual Filesystem."""

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
            # TODO: Determine what the API semantic are and if we should
            # raise an error or not. This requires auditing the client code
            # and callers. (could add exist_ok param etc)
            return existing

        now_ms = int(time.time() * 1000)
        new_dir = UserFileDO(
            user_id=user_id,
            directory_id=parent_id,
            file_name=name,
            is_folder="Y",
            size=0,
            create_time=now_ms,
            update_time=now_ms,
            is_active="Y",
        )
        self.db.add(new_dir)
        await self.db.commit()
        await self.db.refresh(new_dir)
        return new_dir

    async def list_directory(self, user_id: int, parent_id: int) -> list[UserFileDO]:
        """List immediate children of a directory."""
        stmt = select(UserFileDO).where(
            UserFileDO.user_id == user_id,
            UserFileDO.directory_id == parent_id,
            UserFileDO.is_active == "Y",
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_recursive(
        self, user_id: int, parent_id: int, base_path: str = ""
    ) -> list[tuple[UserFileDO, str]]:
        """List all descendants of a directory recursively.

        Returns a list of tuples: (node, relative_path_from_parent).
        """
        results: list[tuple[UserFileDO, str]] = []

        children = await self.list_directory(user_id, parent_id)
        for child in children:
            child_rel_path = (
                f"{base_path}/{child.file_name}" if base_path else child.file_name
            )
            results.append((child, child_rel_path))

            if child.is_folder == "Y":
                sub_results = await self.list_recursive(
                    user_id, child.id, child_rel_path
                )
                results.extend(sub_results)

        return results

    async def create_file(
        self,
        user_id: int,
        parent_id: int,
        name: str,
        size: int,
        md5: str,
        storage_key: str,
    ) -> UserFileDO:
        """Create a file entry (assuming content is handled elsewhere/CAS)."""
        now_ms = int(time.time() * 1000)

        # Check quota (TODO: Implement Capacity check)

        new_file = UserFileDO(
            user_id=user_id,
            directory_id=parent_id,
            file_name=name,
            is_folder="N",
            size=size,
            md5=md5,
            storage_key=storage_key,
            create_time=now_ms,
            update_time=now_ms,
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
        now_ms = int(time.time() * 1000)
        recycle = RecycleFileDO(
            user_id=user_id,
            file_id=node.id,
            file_name=node.file_name,
            size=node.size,
            is_folder=node.is_folder,
            delete_time=now_ms,
        )
        self.db.add(recycle)

        await self.db.commit()
        return True

    async def resolve_path(self, user_id: int, path: str) -> UserFileDO | None:
        """Resolve a posix-style path to a file node."""
        parts = [p for p in path.strip("/").split("/") if p]
        if not parts:
            # Root? We don't have a root node in DB usually (directory_id=0 implies root children)
            # Retuning None might be ambiguous if we expected a node.
            # But technically root doesn't exist as a UserFileDO record.
            return None

        current_dir_id = 0
        current_node = None

        for part in parts:
            stmt = select(UserFileDO).where(
                UserFileDO.user_id == user_id,
                UserFileDO.directory_id == current_dir_id,
                UserFileDO.file_name == part,
                UserFileDO.is_active == "Y",
            )
            result = await self.db.execute(stmt)
            if (node := result.scalar_one_or_none()) is None:
                return None

            current_node = node
            if node.is_folder == "Y":
                current_dir_id = node.id

        return current_node

    async def get_full_path(self, user_id: int, node_id: int) -> str:
        """Resolve the full path of a node by walking up the directory tree."""
        if node_id == 0:
            return ""

        path_parts: list[str] = []
        current_id = node_id

        # Loop until root (0) or not found.
        # Check for circular refs? Simple depth limit could work if needed.
        depth = 0
        max_depth = 50

        while current_id != 0 and depth < max_depth:
            node = await self.get_node_by_id(user_id, current_id)
            if not node:
                # If node is missing mid-tree, we might have a broken tree or root
                # Just return what we have? or broken?
                break

            path_parts.insert(0, node.file_name)
            current_id = node.directory_id
            depth += 1

        return "/".join(path_parts)

    async def ensure_directory_path(self, user_id: int, path: str) -> int:
        """Ensure a directory path exists, creating if necessary. Returns the final directory ID."""
        parts = [p for p in path.strip("/").split("/") if p]
        current_dir_id = 0

        for part in parts:
            stmt = select(UserFileDO).where(
                UserFileDO.user_id == user_id,
                UserFileDO.directory_id == current_dir_id,
                UserFileDO.file_name == part,
                UserFileDO.is_active == "Y",
            )
            result = await self.db.execute(stmt)
            if node := result.scalar_one_or_none():
                if node.is_folder != "Y":
                    raise InvalidPath(f"{part} is a file")
                current_dir_id = node.id
            else:
                # Note: This could likely be made more efficient creating multiple
                # directories in a single transaction.
                new_dir = await self.create_directory(user_id, current_dir_id, part)
                current_dir_id = new_dir.id

        return current_dir_id

    async def move_node(
        self,
        user_id: int,
        node_id: int,
        new_parent_id: int,
        new_name: str,
        autorename: bool = False,
    ) -> UserFileDO | None:
        """Move a node to a new directory."""
        node = await self.get_node_by_id(user_id, node_id)
        if not node:
            return None

        # Cyclic check: ensure new_parent is not a descendant of node
        if node.is_folder == "Y":
            curr_id = new_parent_id
            visited = set()
            while curr_id != 0:
                if curr_id == node.id:
                    raise InvalidPath(
                        "Cyclic move: cannot move a folder into itself or its descendants"
                    )
                if curr_id in visited:
                    raise InvalidPath(
                        f"Cycle detected in move {node_id} -> {new_parent_id} found {curr_id} multiple times"
                    )
                visited.add(curr_id)
                stmt = select(UserFileDO.directory_id).where(
                    UserFileDO.user_id == user_id,
                    UserFileDO.id == curr_id,
                    UserFileDO.is_active == "Y",
                )
                res = await self.db.execute(stmt)
                curr_id = res.scalar() or 0

        # Identity check: if same parent and same name, it's a no-op UNLESS autorename is True
        if (
            not autorename
            and node.directory_id == new_parent_id
            and node.file_name == new_name
        ):
            return node

        # Validate destination
        if new_parent_id != 0:
            parent = await self.get_node_by_id(user_id, new_parent_id)
            if not parent or parent.is_folder == "N":
                raise InvalidPath(
                    f"Invalid destination: folder {new_parent_id} not found"
                )

        # Collision resolution
        if autorename:
            logger.debug("Autorename enabled for move")
            base_name = new_name
            ext = ""
            if "." in base_name and not node.is_folder == "Y":
                parts = base_name.rsplit(".", 1)
                base_name = parts[0]
                ext = f".{parts[1]}"

            counter = 1
            while await self._check_exists(
                user_id, new_parent_id, new_name, node.is_folder
            ):
                new_name = f"{base_name} ({counter}){ext}"
                counter += 1
                if counter > 100:
                    raise FileAlreadyExists(f"File already exists: {new_name}")
        elif await self._check_exists(user_id, new_parent_id, new_name, node.is_folder):
            raise FileAlreadyExists(f"File already exists: {new_name}")

        node.directory_id = new_parent_id
        node.file_name = new_name
        node.update_time = int(time.time() * 1000)

        await self.db.commit()
        return node

    async def copy_node(
        self,
        user_id: int,
        source_node_id: int,
        new_parent_id: int,
        autorename: bool,
        new_name: str,
    ) -> UserFileDO | None:
        """Copy a node recursively."""
        source_node = await self.get_node_by_id(user_id, source_node_id)
        if not source_node:
            return None

        # Collision resolution for the root of the copy
        if autorename:
            logger.debug("Autorename enabled for copy")
            base_name = new_name
            ext = ""
            if "." in base_name and not source_node.is_folder == "Y":
                parts = base_name.rsplit(".", 1)
                base_name = parts[0]
                ext = f".{parts[1]}"

            counter = 1
            while await self._check_exists(
                user_id, new_parent_id, new_name, source_node.is_folder
            ):
                new_name = f"{base_name}({counter}){ext}"
                counter += 1
                if counter > 100:
                    raise FileAlreadyExists(f"File already exists: {new_name}")
        elif await self._check_exists(
            user_id, new_parent_id, new_name, source_node.is_folder
        ):
            raise FileAlreadyExists(f"File already exists: {new_name}")

        now_ms = int(time.time() * 1000)
        new_node = UserFileDO(
            user_id=user_id,
            directory_id=new_parent_id,
            file_name=new_name,
            is_folder=source_node.is_folder,
            size=source_node.size,
            md5=source_node.md5,
            storage_key=source_node.storage_key,
            create_time=now_ms,
            update_time=now_ms,
            is_active="Y",
        )
        self.db.add(new_node)
        await self.db.commit()
        await self.db.refresh(new_node)

        # Recursive copy for folders
        if source_node.is_folder == "Y":
            children = await self.list_directory(user_id, source_node_id)
            for child in children:
                await self.copy_node(
                    user_id=user_id,
                    source_node_id=child.id,
                    new_parent_id=new_node.id,
                    autorename=False,  # Children names are copied exactly within the new folder
                    new_name=child.file_name,
                )

        return new_node

    async def list_recycle(self, user_id: int) -> list[RecycleFileDO]:
        """List files in recycle bin."""
        stmt = select(RecycleFileDO).where(RecycleFileDO.user_id == user_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def restore_node(self, user_id: int, recycle_id: int) -> bool:
        """Restore a file from recycle bin."""
        stmt = select(RecycleFileDO).where(
            RecycleFileDO.user_id == user_id, RecycleFileDO.id == recycle_id
        )
        result = await self.db.execute(stmt)
        if (recycle_entry := result.scalar_one_or_none()) is None:
            return False

        # Get original node
        node_stmt = select(UserFileDO).where(
            UserFileDO.user_id == user_id, UserFileDO.id == recycle_entry.file_id
        )
        node_result = await self.db.execute(node_stmt)
        if node := node_result.scalar_one_or_none():
            node.is_active = "Y"
            # TODO: Lets add common functions for getting the current now_ms so we can
            # fake out update time in tests etc.
            node.update_time = int(time.time() * 1000)

        await self.db.delete(recycle_entry)
        await self.db.commit()
        return True

    async def purge_recycle(
        self, user_id: int, recycle_ids: list[int] | None = None
    ) -> None:
        """Permanently delete items from recycle bin."""

        stmt = delete(RecycleFileDO).where(RecycleFileDO.user_id == user_id)
        if recycle_ids:
            stmt = stmt.where(RecycleFileDO.id.in_(recycle_ids))

        await self.db.execute(stmt)
        # TODO: Also delete UserFileDO? For now, VFS "active='N'" nodes remain.
        await self.db.commit()

    async def search_files(self, user_id: int, keyword: str) -> list[UserFileDO]:
        """Search for active files/folders by keyword (case-insensitive)."""
        stmt = select(UserFileDO).where(
            UserFileDO.user_id == user_id,
            UserFileDO.is_active == "Y",
            UserFileDO.file_name.ilike(f"%{keyword}%"),
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _check_exists(
        self,
        user_id: int,
        parent_id: int,
        name: str,
        is_folder: str,
    ) -> bool:
        """Check if a node exists with the given name in the parent directory."""
        stmt = select(UserFileDO).where(
            UserFileDO.user_id == user_id,
            UserFileDO.directory_id == parent_id,
            UserFileDO.file_name == name,
            UserFileDO.is_active == "Y",
        )
        if is_folder is not None:
            stmt = stmt.where(UserFileDO.is_folder == is_folder)

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_total_usage(self, user_id: int) -> int:
        """Calculate total storage usage for a user in bytes."""
        stmt = select(func.sum(UserFileDO.size)).where(
            UserFileDO.user_id == user_id,
            UserFileDO.is_active == "Y",
            UserFileDO.is_folder == "N",
        )
        result = await self.db.execute(stmt)
        total = result.scalar()
        return total or 0

    async def is_empty(self, user_id: int) -> bool:
        """Check if user has any active files."""
        # Use limit 1 for efficiency
        stmt = (
            select(UserFileDO.id)
            .where(UserFileDO.user_id == user_id, UserFileDO.is_active == "Y")
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.first() is None
