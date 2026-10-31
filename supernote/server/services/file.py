"""High-level file, folder, and recycle bin orchestration service.

`FileService` coordinates metadata operations in `supernote.server.services.vfs.VirtualFileSystem`
with physical blob lifecycle management in `supernote.server.services.blob.BlobStorage`
and quota checks in `supernote.server.services.user.UserService`. When `.note` files or
VFS entries are created, updated, moved, or deleted, `FileService` publishes domain
events (`NoteUpdatedEvent`, `NoteDeletedEvent`, `VfsItemCreatedEvent`, `BlobCleanupEvent`)
onto `supernote.server.events.LocalEventBus` so background processing and Socket.IO
clients stay synchronized. See `supernote.guides.architecture`.
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from supernote.models.base import BooleanEnum
from supernote.server.constants import (
    CACHE_BUCKET,
    CATEGORY_CONTAINERS,
    RECYCLE_RETENTION_MS,
    USER_DATA_BUCKET,
)
from supernote.server.exceptions import (
    AccessDenied,
    FileAlreadyExists,
    FileError,
    FileNotFound,
    HashMismatch,
    InvalidPath,
)
from supernote.server.utils.paths import get_conversion_pdf_path

from ..db.models.file import RecycleFileDO, UserFileDO
from ..db.models.summary import SummaryDO
from ..db.session import DatabaseSessionManager
from ..events import (
    LocalEventBus,
    NoteDeletedEvent,
    NoteUpdatedEvent,
    VfsItemCopiedEvent,
    VfsItemCreatedEvent,
    VfsItemDeletedEvent,
    VfsItemMovedEvent,
)
from .blob import BlobStorage
from .user import UserService
from .vfs import VirtualFileSystem

logger = logging.getLogger(__name__)


__all__ = [
    "FileEntity",
    "FileService",
]


@dataclass
class FileEntity:
    """Domain object representing a file in the system."""

    id: int
    parent_id: int
    name: str
    is_folder: bool
    size: int
    md5: str | None
    create_time: int
    update_time: int
    # Contextual fields computed by the service. This should be the
    # full path of the file in the storage system with no leading or trailing slashes.
    full_path: str
    storage_key: str | None = None

    def __post_init__(self) -> None:
        self.full_path = self.full_path.strip("/")

    @property
    def parent_path(self) -> str:
        """Return the parent path of the file."""
        return str(Path(self.full_path).parent)

    @property
    def tag(self) -> str:
        """Return the tag of the file."""
        return "folder" if self.is_folder else "file"

    @property
    def sort_time(self) -> int:
        """Return the sort time of the file."""
        return self.update_time


def _to_file_entity(node: UserFileDO, full_path: str) -> FileEntity:
    """Convert a UserFileDO to a FileEntity."""
    return FileEntity(
        id=node.id,
        parent_id=node.directory_id,
        name=node.file_name,
        is_folder=bool(node.is_folder == "Y"),
        size=node.size,
        md5=node.md5,
        create_time=int(node.create_time),
        update_time=int(node.update_time),
        full_path=full_path,
        storage_key=node.storage_key,
    )


@dataclass
class RecycleEntity:
    """Domain object representing a file in the system."""

    id: int
    name: str
    is_folder: bool
    size: int
    delete_time: int

    @property
    def sort_time(self) -> int:
        """Return the sort time of the file."""
        return self.delete_time


def _to_recycle_entity(node: RecycleFileDO) -> RecycleEntity:
    """Convert a RecycleFileVO to a FileEntity."""
    return RecycleEntity(
        id=node.id,
        name=node.file_name,
        is_folder=bool(node.is_folder == "Y"),
        size=node.size,
        delete_time=int(node.delete_time),
    )


@dataclass
class PathInfo:
    """Domain object for path information."""

    path: str
    id_path: str


@dataclass
class FolderDetail:
    """Domain object for folder details with metadata."""

    entity: FileEntity
    has_subfolders: bool


@dataclass
class _FileUpsertResult:
    """Result of creating or updating a VFS file node, tracking any superseded artifacts to clean up."""

    node: UserFileDO
    superseded_storage_key: str | None = None
    superseded_md5: str | None = None


class FileService:
    """File service."""

    def __init__(
        self,
        storage_root: Path,
        blob_storage: BlobStorage,
        user_service: UserService,
        session_manager: DatabaseSessionManager,
        event_bus: LocalEventBus | None = None,
    ) -> None:
        """Initialize the file service."""
        self.storage_root = storage_root
        self.blob_storage = blob_storage
        self.user_service = user_service
        self.session_manager = session_manager
        self.event_bus = event_bus

    async def list_folder(
        self, user: str, path_str: str, recursive: bool = False
    ) -> list[FileEntity]:
        """List files in a folder for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        entities: list[FileEntity] = []

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)

            # Resolve parent ID
            clean_path = path_str.strip("/")
            parent_id = 0
            if clean_path:
                if (node := await vfs.resolve_path(user_id, clean_path)) is None:
                    raise FileNotFound(f"Path not found: {clean_path}")
                if node.is_folder != "Y":
                    raise InvalidPath(f"Not a folder: {clean_path}")
                parent_id = node.id

            if recursive:
                recursive_list = await vfs.list_recursive(user_id, parent_id)
                for item, rel_path in recursive_list:
                    full_path = f"{clean_path}/{rel_path}" if clean_path else rel_path
                    entities.append(_to_file_entity(item, full_path))
            else:
                # Flat listing
                do_list = await vfs.list_directory(user_id, parent_id)

                for item in do_list:
                    full_path = (
                        f"{clean_path}/{item.file_name}"
                        if clean_path
                        else item.file_name
                    )
                    entities.append(_to_file_entity(item, full_path))
        return entities

    async def list_folder_by_id(
        self, user: str, folder_id: int, recursive: bool = False
    ) -> list[FileEntity]:
        """List files in a folder by ID for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        entities: list[FileEntity] = []

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)

            # Check if folder exists and verify ownership
            if folder_id != 0:
                node = await vfs.get_node_by_id(user_id, folder_id)
                if not node:
                    raise FileNotFound(f"Folder ID {folder_id} not found")
                if node.is_folder != "Y":
                    raise InvalidPath(f"ID {folder_id} is not a folder")
                # TODO: Retrieve path string for display if needed?
                # For V3 (device), path_display might not be critical or we can construct relative to root?
                # We can't easily rebuild full path without walking up.
                # Assuming devices rely on IDs and relative paths.

            # Resolve base path for the folder
            base_path_display = await vfs.get_full_path(user_id, folder_id)

            if recursive:
                recursive_list = await vfs.list_recursive(user_id, folder_id)
                for item, rel_path in recursive_list:
                    # rel_path is relative to folder_id
                    # if base_path is empty (root), full path is /rel_path
                    # if base_path is /foo, full path is /foo/rel_path
                    base_path_clean = base_path_display.strip("/")
                    full_path = (
                        f"{base_path_clean}/{rel_path}" if base_path_clean else rel_path
                    )
                    entities.append(_to_file_entity(item, full_path))
            else:
                do_list = await vfs.list_directory(user_id, folder_id)
                for item in do_list:
                    base_path_clean = base_path_display.strip("/")
                    full_path = (
                        f"{base_path_clean}/{item.file_name}"
                        if base_path_clean
                        else item.file_name
                    )
                    entities.append(_to_file_entity(item, full_path))
        return entities

    async def get_file_info(self, user: str, path_str: str) -> FileEntity | None:
        """Get file info by path or ID for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)

        # Handle Root
        clean_path = path_str.strip("/")
        if not clean_path:
            # Virtual root directory
            return FileEntity(
                id=0,
                parent_id=-1,  # No parent
                name="",
                is_folder=True,
                size=0,
                md5=None,
                create_time=0,
                update_time=0,
                full_path="",
            )

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            node = await vfs.resolve_path(user_id, path_str)
            if not node:
                return None

            # Always resolve the canonical path from the node structure
            full_path = await vfs.get_full_path(user_id, node.id)

            return _to_file_entity(node, full_path)

    async def get_file_info_by_id(self, user: str, file_id: int) -> FileEntity | None:
        """Get file info by path or ID for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            node = await vfs.get_node_by_id(user_id, file_id)
            if not node:
                return None

            # Always resolve the canonical path from the node structure.
            # This may do a bunch of queries.
            full_path = await vfs.get_full_path(user_id, node.id)

            return _to_file_entity(node, full_path)

    async def get_path_info(self, user: str, node_id: int) -> PathInfo:
        """Resolve both full path and ID path for a node.

        Rules:
        - Both path and idPath do not have any starting or trailing slashes.
        - idPath includes the terminal item ID.
        - idPath does NOT start with the root ID (0/).
        """
        user_id = await self.user_service.get_user_id(user)
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)

            # Resolve paths by walking up to root (directory_id=0)
            path_parts: list[str] = []
            id_path_parts: list[str] = []

            curr_id = node_id
            while curr_id != 0:
                node = await vfs.get_node_by_id(user_id, curr_id)
                if not node:
                    break
                path_parts.insert(0, node.file_name)
                id_path_parts.insert(0, str(node.id))
                curr_id = node.directory_id

            # Construct paths
            path = "/".join(path_parts).strip()
            id_path = "/".join(id_path_parts).strip()
            return PathInfo(path=path, id_path=id_path)

    async def finish_upload(
        self,
        user: str,
        filename: str,
        path_str: str,
        content_hash: str,
        inner_name: str,
    ) -> FileEntity:
        """Finish upload for a specific user."""
        user_id = await self.user_service.get_user_id(user)

        # Verify blob and get metadata
        # We need MD5 to verify integrity
        try:
            metadata = await self.blob_storage.get_metadata(
                USER_DATA_BUCKET, inner_name, include_md5=True
            )
        except FileNotFoundError:
            raise FileNotFound(f"Blob {inner_name} not found")

        if metadata.content_md5 != content_hash:
            raise HashMismatch(
                f"Hash mismatch: expected {content_hash}, got {metadata.content_md5}"
            )

        blob_size = metadata.size

        # Create metadata in VFS
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            clean_path = path_str.strip("/")
            parent_id = 0
            if clean_path:
                parent_id = await vfs.ensure_directory_path(user_id, clean_path)

            upsert_result = await self._upsert_vfs_file(
                vfs=vfs,
                user_id=user_id,
                parent_id=parent_id,
                name=filename,
                size=blob_size,
                md5=content_hash,
                storage_key=inner_name,
            )
            new_file = upsert_result.node
            canonical_full_path = await vfs.get_full_path(user_id, new_file.id)

        await self._cleanup_superseded_artifacts(upsert_result)

        # Construct response
        clean_path = path_str.strip("/")
        full_path = f"{clean_path}/{filename}" if clean_path else filename
        entity = _to_file_entity(new_file, full_path)

        # Emit domain events (fire and forget)
        if self.event_bus:
            if filename.endswith(".note"):
                await self.event_bus.publish(
                    NoteUpdatedEvent(
                        file_id=new_file.id,
                        user_id=user_id,
                        file_path=full_path,
                        defer_processing=True,
                    )
                )
            await self.event_bus.publish(
                VfsItemCreatedEvent(
                    user_id=user_id,
                    item_id=entity.id,
                    parent_id=entity.parent_id,
                    name=entity.name,
                    is_folder=False,
                    full_path=canonical_full_path,
                    size=entity.size,
                    md5=entity.md5,
                )
            )

        return entity

    async def upload_finish_web(
        self,
        user: str,
        directory_id: int,
        file_name: str,
        md5: str,
        inner_name: str,
    ) -> None:
        """Finish upload (Web API)."""
        user_id = await self.user_service.get_user_id(user)

        # Check/promote blob and verify integrity
        try:
            metadata = await self.blob_storage.get_metadata(
                USER_DATA_BUCKET, inner_name, include_md5=True
            )
        except FileNotFoundError:
            raise FileNotFound(f"Blob {inner_name} not found")

        if metadata.content_md5 != md5:
            # Note: The Web API might not expect a HashMismatch error, but it's correct for integrity.
            # Convert to appropriate error if needed, but HashMismatch is fine for now.
            raise HashMismatch(
                f"Hash mismatch: expected {md5}, got {metadata.content_md5}"
            )

        blob_size = metadata.size

        # Create VFS node
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)

            upsert_result = await self._upsert_vfs_file(
                vfs=vfs,
                user_id=user_id,
                parent_id=directory_id,
                name=file_name,
                size=blob_size,
                md5=md5,
                storage_key=inner_name,
            )
            new_file = upsert_result.node

        await self._cleanup_superseded_artifacts(upsert_result)

        # Emit domain events (fire and forget)
        if self.event_bus:
            full_path = await self.get_full_path_by_node(user_id, new_file.id)
            if file_name.endswith(".note"):
                await self.event_bus.publish(
                    NoteUpdatedEvent(
                        file_id=new_file.id, user_id=user_id, file_path=full_path
                    )
                )
            await self.event_bus.publish(
                VfsItemCreatedEvent(
                    user_id=user_id,
                    item_id=new_file.id,
                    parent_id=new_file.directory_id,
                    name=new_file.file_name,
                    is_folder=False,
                    full_path=full_path,
                    size=new_file.size,
                    md5=new_file.md5,
                )
            )

    async def _upsert_vfs_file(
        self,
        vfs: VirtualFileSystem,
        user_id: int,
        parent_id: int,
        name: str,
        size: int,
        md5: str,
        storage_key: str,
    ) -> _FileUpsertResult:
        """Create or update a VFS file node and record any superseded artifacts to clean up."""
        existing = await vfs.get_active_file(user_id, parent_id, name)
        old_storage_key: str | None = existing.storage_key if existing else None
        old_md5: str | None = existing.md5 if existing else None

        new_file = await vfs.create_or_update_file(
            user_id=user_id,
            parent_id=parent_id,
            name=name,
            size=size,
            md5=md5,
            storage_key=storage_key,
        )

        superseded_storage_key = (
            old_storage_key
            if old_storage_key and old_storage_key != storage_key
            else None
        )
        superseded_md5 = old_md5 if old_md5 and old_md5 != md5 else None

        return _FileUpsertResult(
            node=new_file,
            superseded_storage_key=superseded_storage_key,
            superseded_md5=superseded_md5,
        )

    async def _cleanup_superseded_artifacts(
        self,
        result: _FileUpsertResult,
    ) -> None:
        """Delete unreferenced superseded primary blob and stale conversion artifacts."""
        if result.superseded_storage_key:
            await self.cleanup_unreferenced_blobs({result.superseded_storage_key})

        if result.superseded_md5:
            await self._delete_conversion_blobs(
                user_id=result.node.user_id,
                file_id=result.node.id,
                file_md5=result.superseded_md5,
            )

    async def _delete_conversion_blobs(
        self, user_id: int, file_id: int, file_md5: str
    ) -> None:
        """Delete cached on-demand PDF conversion blob for a specific file MD5."""
        pdf_key = get_conversion_pdf_path(
            user_id=user_id, file_id=file_id, file_md5=file_md5
        )
        if await self.blob_storage.exists(CACHE_BUCKET, pdf_key):
            try:
                await self.blob_storage.delete(CACHE_BUCKET, pdf_key)
            except (FileNotFoundError, OSError) as e:
                logger.warning(f"Failed to delete stale conversion blob {pdf_key}: {e}")

    async def create_directory(self, user: str, path: str) -> FileEntity:
        """Create a directory for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        rel_path = path.strip("/")
        if not rel_path:
            raise InvalidPath("Cannot create root directory")

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            existing = await vfs.resolve_path(user_id, rel_path)
            node_id = await vfs.ensure_directory_path(user_id, rel_path)
            node = await vfs.get_node_by_id(user_id, node_id)
            if not node:
                raise FileError(f"Failed to create directory: {rel_path}")
            canonical_full_path = await vfs.get_full_path(user_id, node.id)
            entity = _to_file_entity(node, rel_path)

        if self.event_bus and existing is None:
            await self.event_bus.publish(
                VfsItemCreatedEvent(
                    user_id=user_id,
                    item_id=entity.id,
                    parent_id=entity.parent_id,
                    name=entity.name,
                    is_folder=True,
                    full_path=canonical_full_path,
                )
            )
        return entity

    # TODO: We should be able to share code between the version that creates by path
    # and the version that creates by ID.
    async def create_directory_by_id(
        self, user: str, parent_id: int, name: str
    ) -> FileEntity:
        """Create a directory by parent ID for a specific user."""
        user_id = await self.user_service.get_user_id(user)
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            already_existed = await vfs._check_exists(user_id, parent_id, name, "Y")
            new_dir = await vfs.create_directory(user_id, parent_id, name)
            full_path = await vfs.get_full_path(user_id, new_dir.id)
            entity = _to_file_entity(new_dir, full_path)

        if self.event_bus and not already_existed:
            await self.event_bus.publish(
                VfsItemCreatedEvent(
                    user_id=user_id,
                    item_id=entity.id,
                    parent_id=entity.parent_id,
                    name=entity.name,
                    is_folder=True,
                    full_path=entity.full_path,
                )
            )
        return entity

    async def delete_item(self, email: str, id: int) -> FileEntity:
        """Delete a file or directory for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(email)
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)

            # Immutability check
            node = await vfs.get_node_by_id(user_id, id)
            if not node:
                # Preferring this instead of idempotency for now
                raise FileNotFound(f"Node {id} not found for user {email}")
            if await vfs.is_system_directory(user_id, node):
                raise AccessDenied(f"Cannot delete system directory: {node.file_name}")

            path_display = await vfs.get_full_path(user_id, node.id)
            entity = _to_file_entity(node, path_display)

            success = await vfs.delete_node(user_id, id)
            if not success:
                raise FileNotFound(f"Node {id} not found for user {email}")
        await self.prune_expired_recycle(user_id)
        if self.event_bus:
            await self.event_bus.publish(
                VfsItemDeletedEvent(
                    user_id=user_id,
                    item_id=entity.id,
                    parent_id=entity.parent_id,
                    name=entity.name,
                    full_path=entity.full_path,
                    is_folder=entity.is_folder,
                    size=entity.size,
                    md5=entity.md5,
                )
            )
        return entity

    async def delete_items(self, user: str, id_list: list[int], parent_id: int) -> None:
        """Delete files or directories for a specific user using VFS (Web API)."""
        user_id = await self.user_service.get_user_id(user)
        deleted_entities: list[FileEntity] = []
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            for file_id in id_list:
                # Validate parent ownership/location
                node = await vfs.get_node_by_id(user_id, file_id)
                if not node:
                    continue  # Already gone?

                if node.directory_id != parent_id:
                    # Special case for flattened Web API: allow parent_id=0 if it's a categorized folder
                    is_categorized = False
                    # We need to know if it's a child of a category container
                    async with self.session_manager.session() as sess:
                        vfs_i = VirtualFileSystem(sess)
                        parent_node = await vfs_i.get_node_by_id(
                            user_id, node.directory_id
                        )
                        if parent_node and parent_node.file_name in CATEGORY_CONTAINERS:
                            is_categorized = True

                    if not (parent_id == 0 and is_categorized):
                        raise InvalidPath(
                            f"File {file_id} is not in directory {parent_id}"
                        )

                # Immutability check
                if await vfs.is_system_directory(user_id, node):
                    raise AccessDenied(
                        f"Cannot delete system directory: {node.file_name}"
                    )

                full_path = await vfs.get_full_path(user_id, node.id)
                entity = _to_file_entity(node, full_path)
                if await vfs.delete_node(user_id, file_id):
                    deleted_entities.append(entity)
        await self.prune_expired_recycle(user_id)
        if self.event_bus:
            for entity in deleted_entities:
                await self.event_bus.publish(
                    VfsItemDeletedEvent(
                        user_id=user_id,
                        item_id=entity.id,
                        parent_id=entity.parent_id,
                        name=entity.name,
                        full_path=entity.full_path,
                        is_folder=entity.is_folder,
                        size=entity.size,
                        md5=entity.md5,
                    )
                )

    async def get_storage_usage(self, user: str) -> int:
        """Get total storage usage for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            return await vfs.get_total_usage(user_id)

    async def is_empty(self, user: str) -> bool:
        """Check if user storage is empty using VFS."""
        user_id = await self.user_service.get_user_id(user)
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            return await vfs.is_empty(user_id)

    async def move_items(
        self,
        user: str,
        id_list: list[int],
        target_parent_id: int,
    ) -> None:
        """Batch move items for a specific user."""
        user_id = await self.user_service.get_user_id(user)
        moved_events: list[VfsItemMovedEvent] = []

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            for item_id in id_list:
                node = await vfs.get_node_by_id(user_id, item_id)
                if not node:
                    raise FileNotFound(f"Source item {item_id} not found")

                # Immutability check
                if await vfs.is_system_directory(user_id, node):
                    raise AccessDenied(
                        f"Cannot move system directory: {node.file_name}"
                    )

                original_parent_id = node.directory_id
                original_name = node.file_name
                original_full_path = await vfs.get_full_path(user_id, node.id)

                moved_node = await vfs.move_node(
                    user_id,
                    item_id,
                    target_parent_id,
                    node.file_name,
                    autorename=True,
                )
                if moved_node and (
                    original_parent_id != moved_node.directory_id
                    or original_name != moved_node.file_name
                ):
                    new_full_path = await vfs.get_full_path(user_id, moved_node.id)
                    moved_events.append(
                        VfsItemMovedEvent(
                            user_id=user_id,
                            item_id=moved_node.id,
                            original_parent_id=original_parent_id,
                            new_parent_id=moved_node.directory_id,
                            original_name=original_name,
                            new_name=moved_node.file_name,
                            original_full_path=original_full_path,
                            new_full_path=new_full_path,
                            is_folder=moved_node.is_folder == "Y",
                            size=moved_node.size,
                            md5=moved_node.md5,
                        )
                    )

        if self.event_bus:
            for ev in moved_events:
                await self.event_bus.publish(ev)

    async def move_item(
        self, user: str, item_id: int, to_path: str, autorename: bool = False
    ) -> FileEntity:
        """Move a file or directory for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            node = await vfs.get_node_by_id(user_id, item_id)
            if not node:
                raise FileNotFound(f"Source item {item_id} not found")

            # Immutability check
            if await vfs.is_system_directory(user_id, node):
                raise AccessDenied(f"Cannot move system directory: {node.file_name}")

            original_parent_id = node.directory_id
            original_name = node.file_name
            original_full_path = await vfs.get_full_path(user_id, node.id)

            # Resolve destination parent
            clean_to_path = to_path.strip("/")
            parent_id = 0
            new_name = node.file_name

            if clean_to_path:
                dest_node = await vfs.resolve_path(user_id, clean_to_path)
                if dest_node and dest_node.is_folder == "Y":
                    # Destination is an existing folder, move INTO it
                    parent_id = dest_node.id
                else:
                    # Destination is a new path (rename)
                    parts = clean_to_path.rsplit("/", 1)
                    if len(parts) == 2:
                        parent_path, new_name = parts
                        parent_id = await vfs.ensure_directory_path(
                            user_id, parent_path
                        )
                    else:
                        new_name = parts[0]
                        parent_id = 0

            new_node = await vfs.move_node(
                user_id, item_id, parent_id, new_name, autorename
            )

            if not new_node:
                raise FileError(f"Moving item {item_id} to {parent_id} failed")
            # Re-fetch the new full path for simplicity rather than trying to
            # rebuild it.
            full_path = await vfs.get_full_path(user_id, new_node.id)
            entity = _to_file_entity(new_node, full_path)

        if self.event_bus and (
            original_parent_id != entity.parent_id or original_name != entity.name
        ):
            await self.event_bus.publish(
                VfsItemMovedEvent(
                    user_id=user_id,
                    item_id=entity.id,
                    original_parent_id=original_parent_id,
                    new_parent_id=entity.parent_id,
                    original_name=original_name,
                    new_name=entity.name,
                    original_full_path=original_full_path,
                    new_full_path=entity.full_path,
                    is_folder=entity.is_folder,
                    size=entity.size,
                    md5=entity.md5,
                )
            )
        return entity

    async def copy_items(
        self,
        user: str,
        id_list: list[int],
        target_parent_id: int,
    ) -> None:
        """Batch copy items for a specific user."""
        user_id = await self.user_service.get_user_id(user)
        copied_events: list[VfsItemCopiedEvent] = []

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            for item_id in id_list:
                node = await vfs.get_node_by_id(user_id, item_id)
                if not node:
                    raise FileNotFound(f"Source item {item_id} not found")

                # Check immutability? Usually copy is allowed, but let's be safe.
                # Actually device API copy_item blocks it too.
                if await vfs.is_system_directory(user_id, node):
                    raise AccessDenied(
                        f"Cannot copy system directory: {node.file_name}"
                    )

                source_parent_id = node.directory_id
                original_name = node.file_name
                original_full_path = await vfs.get_full_path(user_id, node.id)

                # Copy logic (no source parent check usually required for copy but we can add it for completeness)
                new_node = await vfs.copy_node(
                    user_id,
                    item_id,
                    target_parent_id,
                    autorename=True,
                    new_name=node.file_name,
                )
                if new_node:
                    new_full_path = await vfs.get_full_path(user_id, new_node.id)
                    copied_events.append(
                        VfsItemCopiedEvent(
                            user_id=user_id,
                            source_id=item_id,
                            new_id=new_node.id,
                            source_parent_id=source_parent_id,
                            new_parent_id=new_node.directory_id,
                            original_name=original_name,
                            new_name=new_node.file_name,
                            original_full_path=original_full_path,
                            new_full_path=new_full_path,
                            is_folder=new_node.is_folder == "Y",
                            size=new_node.size,
                            md5=new_node.md5,
                        )
                    )

        if self.event_bus:
            for ev in copied_events:
                await self.event_bus.publish(ev)

    async def copy_item(
        self, email: str, id: int, to_path: str, autorename: bool
    ) -> FileEntity:
        """Copy a file or directory for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(email)

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            node = await vfs.get_node_by_id(user_id, id)
            if not node:
                raise FileNotFound(f"Source {id} not found")

            # Immutability check
            if await vfs.is_system_directory(user_id, node):
                raise AccessDenied(f"Cannot copy system directory: {node.file_name}")

            source_parent_id = node.directory_id
            original_name = node.file_name
            original_full_path = await vfs.get_full_path(user_id, node.id)

            # Resolve destination parent
            clean_to_path = to_path.strip("/")
            parent_id = 0
            new_name = node.file_name

            if clean_to_path:
                dest_node = await vfs.resolve_path(user_id, clean_to_path)
                if dest_node and dest_node.is_folder == "Y":
                    # Destination is an existing folder, copy INTO it
                    parent_id = dest_node.id
                else:
                    # Destination is a new path (rename)
                    parts = clean_to_path.rsplit("/", 1)
                    if len(parts) == 2:
                        parent_path, new_name = parts
                        parent_id = await vfs.ensure_directory_path(
                            user_id, parent_path
                        )
                    else:
                        new_name = parts[0]
                        parent_id = 0

            new_node = await vfs.copy_node(
                user_id, id, parent_id, autorename=autorename, new_name=new_name
            )

            if not new_node:
                raise FileError(f"Copying item {id} to {parent_id} failed")

            # Re-fetch the new full path for simplicity rather than trying to
            # rebuild it.
            full_path = await vfs.get_full_path(user_id, new_node.id)
            entity = _to_file_entity(new_node, full_path)

        if self.event_bus:
            await self.event_bus.publish(
                VfsItemCopiedEvent(
                    user_id=user_id,
                    source_id=id,
                    new_id=entity.id,
                    source_parent_id=source_parent_id,
                    new_parent_id=entity.parent_id,
                    original_name=original_name,
                    new_name=entity.name,
                    original_full_path=original_full_path,
                    new_full_path=entity.full_path,
                    is_folder=entity.is_folder,
                    size=entity.size,
                    md5=entity.md5,
                )
            )
        return entity

    async def rename_item(self, user: str, id: int, new_name: str) -> None:
        """Rename a file or directory for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            node = await vfs.get_node_by_id(user_id, id)
            if not node:
                raise FileNotFound("Source not found")

            # Immutability check
            if await vfs.is_system_directory(user_id, node):
                raise AccessDenied(f"Cannot rename system directory: {node.file_name}")

            # Check if name already exists in same directory
            exists = await vfs._check_exists(
                user_id, node.directory_id, new_name, node.is_folder
            )
            if exists:
                raise FileAlreadyExists("File already exists")

            original_parent_id = node.directory_id
            original_name = node.file_name
            original_full_path = await vfs.get_full_path(user_id, node.id)

            # Perform rename by updating name in same directory
            # TODO: Verify auto rename behavior here.
            await vfs.move_node(
                user_id, id, node.directory_id, new_name, autorename=False
            )
            new_full_path = await vfs.get_full_path(user_id, node.id)
            entity = _to_file_entity(node, new_full_path)

        if self.event_bus and original_name != entity.name:
            await self.event_bus.publish(
                VfsItemMovedEvent(
                    user_id=user_id,
                    item_id=entity.id,
                    original_parent_id=original_parent_id,
                    new_parent_id=entity.parent_id,
                    original_name=original_name,
                    new_name=entity.name,
                    original_full_path=original_full_path,
                    new_full_path=entity.full_path,
                    is_folder=entity.is_folder,
                    size=entity.size,
                    md5=entity.md5,
                )
            )

    async def get_folders_by_ids(
        self, user: str, parent_id: int, id_list: list[int]
    ) -> list[FolderDetail]:
        """Get details for a list of folders, specialized for Move/Copy dialogs.

        Rules:
        1. id_list is an EXCLUSION filter.
        2. has_subfolders is True if it has subfolders.
        """
        user_id = await self.user_service.get_user_id(user)
        results: list[FolderDetail] = []

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)

            # 1. Fetch all folders in the parent directory
            raw_nodes = await vfs.list_directory(user_id, parent_id)
            nodes = [n for n in raw_nodes if n.is_folder == BooleanEnum.YES]

            # 2. Filter exclusions from id_list
            nodes = [n for n in nodes if n.id not in id_list]
            if not nodes:
                return results

            base_path_clean = (await vfs.get_full_path(user_id, parent_id)).strip("/")

            # 3. Build FolderDetail with lookahead
            for node in nodes:
                # Check for sub-folders (lookahead)
                children = await vfs.list_directory(user_id, node.id)
                has_subfolders = any(c.is_folder == BooleanEnum.YES for c in children)

                # Construct FileEntity
                full_path = (
                    f"{base_path_clean}/{node.file_name}"
                    if base_path_clean
                    else node.file_name
                )

                entity = FileEntity(
                    id=node.id,
                    parent_id=node.directory_id,
                    name=node.file_name,
                    is_folder=True,
                    size=node.size,
                    md5=node.md5,
                    create_time=int(node.create_time),
                    update_time=int(node.update_time),
                    full_path=full_path,
                )

                results.append(
                    FolderDetail(entity=entity, has_subfolders=has_subfolders)
                )

        return results

    async def get_full_path_by_node(self, user_id: int, node_id: int) -> str:
        """Helper to get full path for a node."""
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            return await vfs.get_full_path(user_id, node_id)

    async def list_recycle(self, user: str) -> list[RecycleEntity]:
        """List files in recycle bin for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        await self.prune_expired_recycle(user_id)

        recycle_files: list[RecycleEntity] = []

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            items = await vfs.list_recycle(user_id)

            for item in items:
                recycle_files.append(_to_recycle_entity(item))

        return recycle_files

    async def prune_expired_recycle(self, user_id: int) -> None:
        """Opportunistically purge recycle bin entries older than the retention window."""
        cutoff_ms = int(time.time() * 1000) - RECYCLE_RETENTION_MS
        await self.purge_recycle(user_id=user_id, older_than_ms=cutoff_ms)

    @staticmethod
    async def _filter_unreferenced_summary_keys(
        session: Any, candidate_keys: set[str]
    ) -> set[str]:
        """Return the subset of candidate keys not referenced by any SummaryDO handwriting blob."""
        if not candidate_keys:
            return set()
        summary_stmt = (
            select(SummaryDO.handwrite_inner_name)
            .where(SummaryDO.handwrite_inner_name.in_(candidate_keys))
            .group_by(SummaryDO.handwrite_inner_name)
        )
        surviving_summary_keys = {
            k for k in (await session.execute(summary_stmt)).scalars().all() if k
        }
        return candidate_keys - surviving_summary_keys

    async def cleanup_unreferenced_blobs(self, candidate_keys: set[str]) -> None:
        """Delete candidate keys from USER_DATA_BUCKET that are not referenced by any file or summary row."""
        clean_keys = {k for k in candidate_keys if k}
        if not clean_keys:
            return

        # USER_DATA_BUCKET stores both VFS files (UserFileDO.storage_key) and
        # summary handwriting strokes (SummaryDO.handwrite_inner_name); only delete
        # keys that are unreferenced across both tables.
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            unreferenced_file_keys = await vfs.get_unreferenced_storage_keys(clean_keys)
            blobs_to_delete = await self._filter_unreferenced_summary_keys(
                session, unreferenced_file_keys
            )

        for blob_key in blobs_to_delete:
            try:
                await self.blob_storage.delete(USER_DATA_BUCKET, blob_key)
            except (FileNotFoundError, OSError) as e:
                logger.warning(f"Failed to delete blob {blob_key}: {e}")

    async def purge_recycle(
        self,
        user_id: int,
        recycle_ids: list[int] | None = None,
        older_than_ms: int | None = None,
    ) -> None:
        """Permanently purge items from recycle bin with reference-counted blob cleanup and event publishing."""
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            purged_nodes = await vfs.purge_recycle(
                user_id=user_id,
                recycle_ids=recycle_ids,
                older_than_ms=older_than_ms,
            )
            if not purged_nodes:
                return

            candidate_keys = {
                n.storage_key
                for n in purged_nodes
                if n.is_folder == "N" and n.storage_key
            }

        await self.cleanup_unreferenced_blobs(candidate_keys)

        for node in purged_nodes:
            if node.is_folder == "N" and node.md5:
                await self._delete_conversion_blobs(
                    user_id=node.user_id, file_id=node.id, file_md5=node.md5
                )

        if self.event_bus:
            for node in purged_nodes:
                if node.is_folder == "N" and node.file_name.endswith(".note"):
                    await self.event_bus.publish(
                        NoteDeletedEvent(file_id=node.id, user_id=node.user_id)
                    )

    async def delete_from_recycle(self, user: str, id_list: list[int]) -> None:
        """Permanently delete items from recycle bin for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        await self.purge_recycle(user_id=user_id, recycle_ids=id_list)

    async def revert_from_recycle(self, user: str, id_list: list[int]) -> None:
        """Restore items from recycle bin for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        restored_events: list[VfsItemCreatedEvent] = []
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            recycle_map = {r.id: r.file_id for r in await vfs.list_recycle(user_id)}
            for recycle_id in id_list:
                restored = await vfs.restore_node(user_id, recycle_id)
                file_id = recycle_map.get(recycle_id)
                if restored and file_id is not None:
                    node = await vfs.get_node_by_id(user_id, file_id)
                    if node is not None:
                        full_path = await vfs.get_full_path(user_id, node.id)
                        restored_events.append(
                            VfsItemCreatedEvent(
                                user_id=user_id,
                                item_id=node.id,
                                parent_id=node.directory_id,
                                name=node.file_name,
                                is_folder=node.is_folder == "Y",
                                full_path=full_path,
                                size=node.size,
                                md5=node.md5,
                            )
                        )
        if self.event_bus:
            for ev in restored_events:
                await self.event_bus.publish(ev)

    async def clear_recycle(self, user: str) -> None:
        """Empty the recycle bin for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        await self.purge_recycle(user_id=user_id)

    async def search_files(self, user: str, keyword: str) -> list[FileEntity]:
        """Search for files matching the keyword in user's storage.

        Args:
            user: User email.
            keyword: Search keyword.
        """
        user_id = await self.user_service.get_user_id(user)
        results: list[FileEntity] = []

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            do_list = await vfs.search_files(user_id, keyword)
            parent_paths: dict[int, str] = {0: ""}

            for item in do_list:
                dir_id = item.directory_id
                if dir_id not in parent_paths:
                    parent_paths[dir_id] = (
                        await vfs.get_full_path(user_id, dir_id)
                    ).strip("/")
                base_path = parent_paths[dir_id]
                full_path = (
                    f"{base_path}/{item.file_name}" if base_path else item.file_name
                )
                results.append(_to_file_entity(item, full_path))

        return results

    async def query_file_list(
        self,
        user: str,
        directory_id: int,
    ) -> list[FileEntity]:
        """Query files in a directory for a specific user."""
        user_id = await self.user_service.get_user_id(user)

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            items = await vfs.list_directory(user_id, directory_id)
            if not items:
                return []

            folder_ids = [item.id for item in items if item.is_folder == "Y"]
            folder_sizes = (
                await vfs.get_folder_sizes(user_id, folder_ids) if folder_ids else {}
            )

            base_path_clean = (await vfs.get_full_path(user_id, directory_id)).strip(
                "/"
            )

            # Mapping to FileEntity
            file_entities: list[FileEntity] = []
            for item in items:
                full_path = (
                    f"{base_path_clean}/{item.file_name}"
                    if base_path_clean
                    else item.file_name
                )
                entity = _to_file_entity(item, full_path)
                if entity.is_folder:
                    entity.size = folder_sizes.get(entity.id, 0)
                file_entities.append(entity)

            return file_entities
