"""Transactional SQLite-backed Virtual File System (`VirtualFileSystem`).

`VirtualFileSystem` implements path resolution, directory creation, atomic move/copy,
recycle bin soft-deletion (`RecycleFileDO`), and system directory protection
(`NOTE`, `DOCUMENT`, `EXPORT`, `INBOX`, `SCREENSHOT`) over `supernote.server.db.models.file.UserFileDO`
rows without mirroring folders on the physical filesystem. Wrapped by
`supernote.server.services.file.FileService`. See `supernote.guides.architecture`.
"""

import logging
import time
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from supernote.server.constants import (
    SYSTEM_CATEGORY_CONTAINER_MAP,
    SYSTEM_ROOT_DIRECTORIES,
)
from supernote.server.db.models.file import RecycleFileDO, UserFileDO
from supernote.server.exceptions import FileAlreadyExists, InvalidPath, ParentNotFound

logger = logging.getLogger(__name__)


class VirtualFileSystem:
    """Core implementation of the Database-Driven Virtual Filesystem."""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def _resolve_root_segment(
        self, user_id: int, segment: str
    ) -> UserFileDO | None:
        """Resolve a root path segment to a directory/file node.

        Checks direct children at root (directory_id=0) first. If not found and the segment
        matches a known category subfolder (Note, MyStyle, Document), checks inside its
        explicit parent container (NOTE or DOCUMENT).
        """
        stmt = select(UserFileDO).where(
            UserFileDO.user_id == user_id,
            UserFileDO.directory_id == 0,
            UserFileDO.file_name == segment,
            UserFileDO.is_active == "Y",
        )
        result = await self.db.execute(stmt)
        if node := result.scalar_one_or_none():
            return node

        if target_container := SYSTEM_CATEGORY_CONTAINER_MAP.get(segment):
            category_parent = (
                select(UserFileDO.id)
                .where(
                    UserFileDO.user_id == user_id,
                    UserFileDO.directory_id == 0,
                    UserFileDO.file_name == target_container,
                    UserFileDO.is_active == "Y",
                    UserFileDO.is_folder == "Y",
                )
                .scalar_subquery()
            )
            stmt = select(UserFileDO).where(
                UserFileDO.user_id == user_id,
                UserFileDO.directory_id == category_parent,
                UserFileDO.file_name == segment,
                UserFileDO.is_active == "Y",
            )
            result = await self.db.execute(stmt)
            return result.scalar_one_or_none()

        return None

    async def is_system_directory(self, user_id: int, node: UserFileDO) -> bool:
        """Whether `node` is a folder a Supernote device requires.

        These are Export, Inbox and Screenshot at the root, and Note, MyStyle and
        Document inside the NOTE and DOCUMENT containers. The same names
        elsewhere are ordinary folders.
        """
        if node.is_folder != "Y":
            return False

        name = node.file_name
        if node.directory_id == 0:
            return name in SYSTEM_ROOT_DIRECTORIES

        container = SYSTEM_CATEGORY_CONTAINER_MAP.get(name)
        if container is None:
            return False

        parent_node = await self.get_node_by_id(user_id, node.directory_id)
        return (
            parent_node is not None
            and parent_node.directory_id == 0
            and parent_node.file_name == container
        )

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
        stmt = (
            select(UserFileDO)
            .where(
                UserFileDO.user_id == user_id,
                UserFileDO.is_active == "Y",
            )
            .order_by(UserFileDO.id)
        )
        all_nodes = (await self.db.execute(stmt)).scalars().all()
        by_parent: dict[int, list[UserFileDO]] = {}
        for node in all_nodes:
            by_parent.setdefault(node.directory_id, []).append(node)

        results: list[tuple[UserFileDO, str]] = []

        def _walk(curr_parent_id: int, curr_base: str) -> None:
            for child in by_parent.get(curr_parent_id, ()):
                child_rel_path = (
                    f"{curr_base}/{child.file_name}" if curr_base else child.file_name
                )
                results.append((child, child_rel_path))
                if child.is_folder == "Y":
                    _walk(child.id, child_rel_path)

        _walk(parent_id, base_path)
        return results

    async def get_active_file(
        self, user_id: int, parent_id: int, name: str
    ) -> UserFileDO | None:
        """Return the active non-folder file in the given directory if it exists."""
        stmt = (
            select(UserFileDO)
            .where(
                UserFileDO.user_id == user_id,
                UserFileDO.directory_id == parent_id,
                UserFileDO.file_name == name,
                UserFileDO.is_active == "Y",
                UserFileDO.is_folder == "N",
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_unreferenced_storage_keys(self, candidate_keys: set[str]) -> set[str]:
        """Return the subset of candidate storage keys not referenced by any UserFileDO row."""
        if not candidate_keys:
            return set()
        stmt = (
            select(UserFileDO.storage_key)
            .where(UserFileDO.storage_key.in_(candidate_keys))
            .group_by(UserFileDO.storage_key)
        )
        surviving_keys = {
            k for k in (await self.db.execute(stmt)).scalars().all() if k is not None
        }
        return candidate_keys - surviving_keys

    async def create_or_update_file(
        self,
        user_id: int,
        parent_id: int,
        name: str,
        size: int,
        md5: str,
        storage_key: str,
    ) -> UserFileDO:
        """Create or update a file entry (assuming content is handled elsewhere/CAS)."""
        now_ms = int(time.time() * 1000)

        existing = await self.get_active_file(user_id, parent_id, name)
        if existing:
            # Overwrite/update the existing active file entry
            existing.size = size
            existing.md5 = md5
            existing.storage_key = storage_key
            existing.update_time = now_ms
            await self.db.commit()
            await self.db.refresh(existing)
            return existing

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

    async def get_node_by_id(self, user_id: int, node_id: int) -> UserFileDO | None:
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

        now_ms = int(time.time() * 1000)
        node.is_active = "N"
        node.update_time = now_ms

        # Create recycle bin entry
        recycle = RecycleFileDO(
            user_id=user_id,
            file_id=node.id,
            file_name=node.file_name,
            size=node.size,
            is_folder=node.is_folder,
            delete_time=now_ms,
        )
        self.db.add(recycle)

        if node.is_folder == "Y":
            await self._cascade_soft_delete(user_id, node.id, now_ms)

        await self.db.commit()
        return True

    async def _cascade_soft_delete(
        self, user_id: int, folder_id: int, now_ms: int
    ) -> None:
        """Cascade inactivation across all active descendants of a folder."""
        queue = [folder_id]
        visited = {folder_id}
        while queue:
            current_id = queue.pop(0)
            stmt = select(UserFileDO).where(
                UserFileDO.user_id == user_id,
                UserFileDO.directory_id == current_id,
                UserFileDO.is_active == "Y",
            )
            result = await self.db.execute(stmt)
            children = result.scalars().all()
            for child in children:
                child.is_active = "N"
                child.update_time = now_ms
                if child.is_folder == "Y" and child.id not in visited:
                    visited.add(child.id)
                    queue.append(child.id)

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

        for i, part in enumerate(parts):
            if i == 0 and current_dir_id == 0:
                node = await self._resolve_root_segment(user_id, part)
            else:
                stmt = select(UserFileDO).where(
                    UserFileDO.user_id == user_id,
                    UserFileDO.directory_id == current_dir_id,
                    UserFileDO.file_name == part,
                    UserFileDO.is_active == "Y",
                )
                result = await self.db.execute(stmt)
                node = result.scalar_one_or_none()

            if node is None:
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

        for i, part in enumerate(parts):
            node: UserFileDO | None = None
            if i == 0 and current_dir_id == 0:
                node = await self._resolve_root_segment(user_id, part)

            if node is None:
                stmt = select(UserFileDO).where(
                    UserFileDO.user_id == user_id,
                    UserFileDO.directory_id == current_dir_id,
                    UserFileDO.file_name == part,
                    UserFileDO.is_active == "Y",
                )
                result = await self.db.execute(stmt)
                node = result.scalar_one_or_none()

            if node:
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
        node = node_result.scalar_one_or_none()
        if node is None:
            return False

        # Check parent directory existence and active status
        if node.directory_id != 0:
            parent_stmt = select(UserFileDO).where(
                UserFileDO.user_id == user_id,
                UserFileDO.id == node.directory_id,
            )
            parent_result = await self.db.execute(parent_stmt)
            parent = parent_result.scalar_one_or_none()
            if parent is None or parent.is_active != "Y" or parent.is_folder != "Y":
                raise ParentNotFound("Parent directory is missing")

        now_ms = int(time.time() * 1000)
        node.is_active = "Y"
        node.update_time = now_ms

        await self.db.delete(recycle_entry)

        # Reactivate descendants that were cascade-deleted with the folder.
        # Descendants with an existing RecycleFileDO entry were deleted independently
        # and must remain inactive in the recycle bin.
        if node.is_folder == "Y":
            recycle_stmt = select(RecycleFileDO.file_id).where(
                RecycleFileDO.user_id == user_id,
                RecycleFileDO.id != recycle_entry.id,
            )
            independently_deleted_ids = set(
                (await self.db.execute(recycle_stmt)).scalars().all()
            )

            queue = [node.id]
            visited = {node.id}
            while queue:
                current_id = queue.pop(0)
                cascade_stmt = select(UserFileDO).where(
                    UserFileDO.user_id == user_id,
                    UserFileDO.directory_id == current_id,
                    UserFileDO.is_active == "N",
                )
                cascade_res = await self.db.execute(cascade_stmt)
                children = cascade_res.scalars().all()
                for child in children:
                    if child.id in independently_deleted_ids:
                        # Independently deleted by user; keep inactive in recycle bin
                        continue
                    child.is_active = "Y"
                    child.update_time = now_ms
                    if child.is_folder == "Y" and child.id not in visited:
                        visited.add(child.id)
                        queue.append(child.id)

        await self.db.commit()
        return True

    async def purge_recycle(
        self,
        user_id: int,
        recycle_ids: list[int] | None = None,
        older_than_ms: int | None = None,
    ) -> list[UserFileDO]:
        """Permanently delete items from recycle bin and return purged file nodes."""
        stmt = select(RecycleFileDO).where(RecycleFileDO.user_id == user_id)
        if recycle_ids is not None:
            if not recycle_ids:
                return []
            stmt = stmt.where(RecycleFileDO.id.in_(recycle_ids))
        if older_than_ms is not None:
            stmt = stmt.where(RecycleFileDO.delete_time < older_than_ms)
        recycle_entries = list((await self.db.execute(stmt)).scalars().all())
        if not recycle_entries:
            return []

        target_file_ids = [r.file_id for r in recycle_entries]
        node_stmt = select(UserFileDO).where(
            UserFileDO.user_id == user_id,
            UserFileDO.id.in_(target_file_ids),
        )
        primary_nodes = list((await self.db.execute(node_stmt)).scalars().all())

        all_nodes: dict[int, UserFileDO] = {n.id: n for n in primary_nodes}
        folder_queue = [n.id for n in primary_nodes if n.is_folder == "Y"]
        while folder_queue:
            desc_stmt = select(UserFileDO).where(
                UserFileDO.user_id == user_id,
                UserFileDO.directory_id.in_(folder_queue),
            )
            desc_nodes = (await self.db.execute(desc_stmt)).scalars().all()
            folder_queue = []
            for desc in desc_nodes:
                if desc.id not in all_nodes:
                    all_nodes[desc.id] = desc
                    if desc.is_folder == "Y":
                        folder_queue.append(desc.id)

        all_file_ids = set(all_nodes.keys()) | set(target_file_ids)
        await self.db.execute(
            delete(RecycleFileDO).where(
                RecycleFileDO.user_id == user_id,
                RecycleFileDO.file_id.in_(all_file_ids),
            )
        )
        await self.db.execute(
            delete(UserFileDO).where(
                UserFileDO.user_id == user_id,
                UserFileDO.id.in_(all_file_ids),
            )
        )
        await self.db.commit()
        return list(all_nodes.values())

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

    async def get_folder_sizes(
        self, user_id: int, folder_ids: Sequence[int]
    ) -> dict[int, int]:
        """Calculate recursive total file byte sizes for each folder in folder_ids."""
        if not folder_ids:
            return {}

        unique_ids = list(set(folder_ids))
        base = (
            select(
                UserFileDO.directory_id.label("root_folder_id"),
                UserFileDO.id,
                UserFileDO.is_folder,
                UserFileDO.size,
            )
            .where(
                UserFileDO.user_id == user_id,
                UserFileDO.is_active == "Y",
                UserFileDO.directory_id.in_(unique_ids),
            )
            .cte(name="folder_descendants", recursive=True)
        )

        child = aliased(UserFileDO)
        descendants = base.union_all(
            select(
                base.c.root_folder_id,
                child.id,
                child.is_folder,
                child.size,
            ).where(
                child.user_id == user_id,
                child.is_active == "Y",
                base.c.is_folder == "Y",
                child.directory_id == base.c.id,
            )
        )

        stmt = (
            select(
                descendants.c.root_folder_id,
                func.coalesce(func.sum(descendants.c.size), 0),
            )
            .where(descendants.c.is_folder == "N")
            .group_by(descendants.c.root_folder_id)
        )

        result = await self.db.execute(stmt)
        sizes: dict[int, int] = {fid: 0 for fid in unique_ids}
        for root_folder_id, total_size in result.all():
            sizes[int(root_folder_id)] = int(total_size or 0)
        return sizes

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
