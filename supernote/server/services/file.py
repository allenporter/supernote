import asyncio
import hashlib
import logging
import shutil
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import aiofiles

from supernote.models.base import BaseResponse, BooleanEnum, create_error_response
from supernote.server.constants import (
    CATEGORY_CONTAINERS,
    IMMUTABLE_SYSTEM_DIRECTORIES,
)

from ..db.models.file import RecycleFileDO, UserFileDO
from ..db.session import DatabaseSessionManager
from .blob import BlobStorage
from .user import UserService
from .vfs import VirtualFileSystem

logger = logging.getLogger(__name__)


__all__ = [
    "FileService",
    "FileEntity",
    "FileServiceException",
    "InvalidPathException",
]


class FileServiceException(Exception):
    """Exception raised by file service."""


class InvalidPathException(FileServiceException):
    """Exception raised when an invalid path is provided."""


class HashMismatchException(FileServiceException):
    """Exception raised when a hash mismatch is detected."""


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


class FileService:
    """File service."""

    def __init__(
        self,
        storage_root: Path,
        blob_storage: BlobStorage,
        user_service: UserService,
        session_manager: DatabaseSessionManager,
    ) -> None:
        """Initialize the file service."""
        self.storage_root = storage_root
        self.blob_storage = blob_storage
        self.temp_dir = storage_root / "temp"
        self.user_service = user_service
        self.session_manager = session_manager
        self.temp_dir.mkdir(parents=True, exist_ok=True)

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
                    # Path not found
                    return []
                if node.is_folder != "Y":
                    # Not a folder
                    return []
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
                    # Not found or not owned
                    return []
                if node.is_folder != "Y":
                    return []
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
    ) -> FileEntity:
        """Finish upload for a specific user."""
        # 1. Resolve User ID
        user_id = await self.user_service.get_user_id(user)

        # 2. Check if Blob exists (CAS)
        if not await self.blob_storage.exists(content_hash):
            # Fallback: check legacy temp file from save_temp_file
            temp_path = self.resolve_temp_path(user, filename)
            if await asyncio.to_thread(temp_path.exists):
                # Calculate MD5 and promote to blob
                hash_md5 = hashlib.md5()
                async with aiofiles.open(temp_path, "rb") as f:
                    while True:
                        chunk = await f.read(4096)
                        if not chunk:
                            break
                        hash_md5.update(chunk)
                calc_md5 = hash_md5.hexdigest()

                if calc_md5 != content_hash:
                    raise ValueError(
                        f"Hash mismatch: expected {content_hash}, got {calc_md5}"
                    )

                # Write to blob
                async with aiofiles.open(temp_path, "rb") as f:
                    data = await f.read()
                    await self.blob_storage.write_blob(data)

                # Cleanup temp
                await asyncio.to_thread(temp_path.unlink, missing_ok=True)
            else:
                raise FileNotFoundError(
                    f"Blob {content_hash} not found and no temp file."
                )

        # 3. Create Metadata in VFS
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            clean_path = path_str.strip("/")
            parent_id = 0
            if clean_path:
                parent_id = await vfs.ensure_directory_path(user_id, clean_path)

            blob_size = self.blob_storage.get_blob_path(content_hash).stat().st_size

            new_file = await vfs.create_file(
                user_id=user_id,
                parent_id=parent_id,
                name=filename,
                size=blob_size,
                md5=content_hash,
            )

        # 4. Construct response
        clean_path = path_str.strip("/")
        full_path = f"{clean_path}/{filename}" if clean_path else filename

        return _to_file_entity(new_file, full_path)

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

        # 1. Check/Promote Blob
        # Note: We use inner_name to find the temp file if not in blob storage
        if not await self.blob_storage.exists(md5):
            temp_path = self.resolve_temp_path(user, inner_name)
            if await asyncio.to_thread(temp_path.exists):
                # Validate MD5
                hash_md5 = hashlib.md5()
                async with aiofiles.open(temp_path, "rb") as f:
                    while True:
                        chunk = await f.read(4096)
                        if not chunk:
                            break
                        hash_md5.update(chunk)
                calc_md5 = hash_md5.hexdigest()

                if calc_md5 != md5:
                    raise HashMismatchException(
                        f"Hash mismatch: expected {md5}, got {calc_md5}"
                    )

                # Promote to Blob
                async with aiofiles.open(temp_path, "rb") as f:
                    data = await f.read()
                    await self.blob_storage.write_blob(data)

                await asyncio.to_thread(temp_path.unlink, missing_ok=True)
            else:
                # If neither blob nor temp file exists -> error
                raise InvalidPathException(
                    f"Blob {md5} not found and temporary file {inner_name} missing."
                )

        # 2. Create VFS Node
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            # Verify directory exists? (Optional, create_file might check FK or fail)
            # create_file expects valid parent_id.

            # Using actual size from blob or DTO? DTO usually trusted or verified during promotion.
            # Ideally verify blob size.
            blob_size = self.blob_storage.get_blob_path(md5).stat().st_size

            await vfs.create_file(
                user_id=user_id,
                parent_id=directory_id,
                name=file_name,
                size=blob_size,
                md5=md5,
            )

    async def create_directory(self, user: str, path: str) -> FileEntity:
        """Create a directory for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        rel_path = path.strip("/")
        if not rel_path:
            raise InvalidPathException("Cannot create root directory")

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            node_id = await vfs.ensure_directory_path(user_id, rel_path)
            node = await vfs.get_node_by_id(user_id, node_id)
            if not node:
                raise InvalidPathException(f"Failed to create directory: {rel_path}")

            return _to_file_entity(node, rel_path)

    # TODO: We should be able to share code between the version that creates by path
    # and the version that creates by ID.
    async def create_directory_by_id(
        self, user: str, parent_id: int, name: str
    ) -> FileEntity:
        """Create a directory by parent ID for a specific user."""
        user_id = await self.user_service.get_user_id(user)
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            new_dir = await vfs.create_directory(user_id, parent_id, name)
            full_path = await vfs.get_full_path(user_id, new_dir.id)

            return _to_file_entity(new_dir, full_path)

    async def delete_item(self, email: str, id: int) -> FileEntity:
        """Delete a file or directory for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(email)
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)

            # Immutability check
            node = await vfs.get_node_by_id(user_id, id)
            if not node:
                # Preferring this instead of idempotency for now
                raise InvalidPathException(f"Node {id} not found for user {email}")
            if node.file_name in IMMUTABLE_SYSTEM_DIRECTORIES:
                raise InvalidPathException(
                    f"Cannot delete system directory: {node.file_name}"
                )

            path_display = await vfs.get_full_path(user_id, node.id)
            entity = _to_file_entity(node, path_display)

            success = await vfs.delete_node(user_id, id)
            if not success:
                raise InvalidPathException(f"Node {id} not found for user {email}")
            return entity

    async def delete_items(
        self, user: str, id_list: list[int], parent_id: int
    ) -> BaseResponse:
        """Delete files or directories for a specific user using VFS (Web API)."""
        user_id = await self.user_service.get_user_id(user)
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
                        return create_error_response(
                            f"File {file_id} is not in directory {parent_id}", "E400"
                        )

                # Immutability check
                if node.file_name in IMMUTABLE_SYSTEM_DIRECTORIES:
                    raise InvalidPathException(
                        f"Cannot delete system directory: {node.file_name}"
                    )

                await vfs.delete_node(user_id, file_id)

        return BaseResponse()

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

    # --- Chunk / Temp File Management (Moved from StorageService) ---

    def resolve_temp_path(self, user: str, filename: str) -> Path:
        """Resolve a filename to an absolute path in user's temp storage."""
        return self.temp_dir / user / filename

    def get_chunk_path(
        self, user: str, upload_id: str, filename: str, part_number: int
    ) -> Path:
        """Get path for a chunk."""
        chunk_filename = f"{filename}_chunk_{part_number}"
        return self.temp_dir / user / upload_id / chunk_filename

    async def save_temp_file(
        self, user: str, filename: str, chunk_reader: Callable[[], Awaitable[bytes]]
    ) -> tuple[int, str]:
        """Save data to user's temp file. Returns (total_bytes, md5_hash)."""
        temp_path = self.resolve_temp_path(user, filename)
        temp_path.parent.mkdir(parents=True, exist_ok=True)

        loop = asyncio.get_running_loop()
        f = await loop.run_in_executor(None, open, temp_path, "wb")
        total_bytes = 0
        hash_md5 = hashlib.md5()
        try:
            while True:
                chunk = await chunk_reader()
                if not chunk:
                    break
                await loop.run_in_executor(None, f.write, chunk)
                hash_md5.update(chunk)
                total_bytes += len(chunk)
        finally:
            await loop.run_in_executor(None, f.close)
        return total_bytes, hash_md5.hexdigest()

    async def save_chunk_file(
        self,
        user: str,
        upload_id: str,
        filename: str,
        part_number: int,
        chunk_reader: Callable[[], Awaitable[bytes]],
    ) -> tuple[int, str]:
        """Save a single chunk. Returns (total_bytes, md5_hash)."""
        chunk_path = self.get_chunk_path(user, upload_id, filename, part_number)
        chunk_path.parent.mkdir(parents=True, exist_ok=True)

        loop = asyncio.get_running_loop()
        f = await loop.run_in_executor(None, open, chunk_path, "wb")
        total_bytes = 0
        hash_md5 = hashlib.md5()
        try:
            while True:
                chunk = await chunk_reader()
                if not chunk:
                    break
                await loop.run_in_executor(None, f.write, chunk)
                hash_md5.update(chunk)
                total_bytes += len(chunk)
        finally:
            await loop.run_in_executor(None, f.close)

        chunk_md5 = hash_md5.hexdigest()
        logger.info(
            f"Saved chunk {part_number} for {filename} (user: {user}): {total_bytes} bytes, MD5: {chunk_md5}"
        )
        return total_bytes, chunk_md5

    async def merge_chunks(
        self, user: str, upload_id: str, filename: str, total_chunks: int
    ) -> str:
        """Merge chunks into BlobStorage. Returns MD5."""
        logger.info(f"Merging {total_chunks} chunks for {filename} (user: {user})")

        async def chunk_stream() -> AsyncGenerator[bytes, None]:
            for part_number in range(1, total_chunks + 1):
                chunk_path = self.get_chunk_path(user, upload_id, filename, part_number)
                if not chunk_path.exists():
                    raise FileNotFoundError(f"Chunk {part_number} not found")

                async with aiofiles.open(chunk_path, "rb") as f:
                    while True:
                        data = await f.read(8192)
                        if not data:
                            break
                        yield data

        md5 = await self.blob_storage.write_stream(chunk_stream())
        logger.info(f"Merged chunks for {filename}, MD5: {md5}")
        return md5

    def cleanup_chunks(self, user: str, upload_id: str) -> None:
        """Delete upload directory."""
        upload_dir = self.temp_dir / user / upload_id
        if upload_dir.exists():
            try:
                shutil.rmtree(upload_dir)
            except OSError as e:
                logger.warning(f"Failed to cleanup chunks {upload_id}: {e}")

    async def move_items(
        self,
        user: str,
        id_list: list[int],
        target_parent_id: int,
    ) -> BaseResponse:
        """Batch move items for a specific user."""
        user_id = await self.user_service.get_user_id(user)

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            for item_id in id_list:
                node = await vfs.get_node_by_id(user_id, item_id)
                if not node:
                    return create_error_response(
                        f"Source item {item_id} not found", "E404"
                    )

                # Immutability check
                if node.file_name in IMMUTABLE_SYSTEM_DIRECTORIES:
                    return create_error_response(
                        f"Cannot move system directory: {node.file_name}",
                        "E_SYSTEM_DIR",
                    )

                try:
                    await vfs.move_node(
                        user_id,
                        item_id,
                        target_parent_id,
                        node.file_name,
                        autorename=True,
                    )
                except ValueError as e:
                    return create_error_response(str(e), "E400")

        return BaseResponse(success=True)

    async def move_item(
        self, user: str, item_id: int, to_path: str, autorename: bool = False
    ) -> FileEntity:
        """Move a file or directory for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            node = await vfs.get_node_by_id(user_id, item_id)
            if not node:
                raise InvalidPathException(f"Source item {item_id} not found")

            # Immutability check
            if node.file_name in IMMUTABLE_SYSTEM_DIRECTORIES:
                raise InvalidPathException(
                    f"Cannot move system directory: {node.file_name}"
                )

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

            try:
                new_node = await vfs.move_node(
                    user_id, item_id, parent_id, new_name, autorename
                )
            except ValueError as e:
                raise InvalidPathException(str(e))
            except FileExistsError as e:
                # Device API conflict error is usually E0322, which we can map to InvalidPathException
                # or a specialized conflict exception if we had one.
                # For now, InvalidPathException will be caught and return 400 or 409 depending on handler.
                raise InvalidPathException(f"Conflict: {str(e)}")

            if not new_node:
                raise FileServiceException(
                    f"Moving item {item_id} to {parent_id} failed"
                )
            # Re-fetch the new full path for simplicity rather than trying to
            # rebuild it.
            full_path = await vfs.get_full_path(user_id, new_node.id)
            return _to_file_entity(new_node, full_path)

    async def copy_items(
        self,
        user: str,
        id_list: list[int],
        target_parent_id: int,
    ) -> BaseResponse:
        """Batch copy items for a specific user."""
        user_id = await self.user_service.get_user_id(user)

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            for item_id in id_list:
                node = await vfs.get_node_by_id(user_id, item_id)
                if not node:
                    return create_error_response(
                        f"Source item {item_id} not found", "E404"
                    )

                # Check immutability? Usually copy is allowed, but let's be safe.
                # Actually device API copy_item blocks it too.
                if node.file_name in IMMUTABLE_SYSTEM_DIRECTORIES:
                    return create_error_response(
                        f"Cannot copy system directory: {node.file_name}",
                        "E_SYSTEM_DIR",
                    )

                # Copy logic (no source parent check usually required for copy but we can add it for completeness)
                try:
                    await vfs.copy_node(
                        user_id,
                        item_id,
                        target_parent_id,
                        autorename=True,
                        new_name=node.file_name,
                    )
                except ValueError as e:
                    return create_error_response(str(e), "E400")

        return BaseResponse(success=True)

    async def copy_item(
        self, email: str, id: int, to_path: str, autorename: bool
    ) -> FileEntity:
        """Copy a file or directory for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(email)

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            node = await vfs.get_node_by_id(user_id, id)
            if not node:
                raise InvalidPathException(f"Source {id} not found")

            # Immutability check
            if node.file_name in IMMUTABLE_SYSTEM_DIRECTORIES:
                raise InvalidPathException(
                    f"Cannot copy system directory: {node.file_name}"
                )

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

            try:
                new_node = await vfs.copy_node(
                    user_id, id, parent_id, autorename=autorename, new_name=new_name
                )
            except FileExistsError as e:
                raise InvalidPathException(f"Conflict: {str(e)}")

            if not new_node:
                raise FileServiceException(f"Copying item {id} to {parent_id} failed")

            # Re-fetch the new full path for simplicity rather than trying to
            # rebuild it.
            full_path = await vfs.get_full_path(user_id, new_node.id)
            return _to_file_entity(new_node, full_path)

    async def rename_item(self, user: str, id: int, new_name: str) -> BaseResponse:
        """Rename a file or directory for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            node = await vfs.get_node_by_id(user_id, id)
            if not node:
                return create_error_response("Source not found", "E404")

            # Immutability check
            if node.file_name in IMMUTABLE_SYSTEM_DIRECTORIES:
                return create_error_response(
                    f"Cannot rename system directory: {node.file_name}", "E_SYSTEM_DIR"
                )

            # Check if name already exists in same directory
            exists = await vfs._check_exists(
                user_id, node.directory_id, new_name, node.is_folder
            )
            if exists:
                return create_error_response("File already exists", "E409")

            # Perform rename by updating name in same directory
            # TODO: Verify auto rename behavior here.
            await vfs.move_node(
                user_id, id, node.directory_id, new_name, autorename=False
            )

        return BaseResponse(success=True)

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

            # 3. Build FolderDetail with lookahead
            for node in nodes:
                # Check for sub-folders (lookahead)
                children = await vfs.list_directory(user_id, node.id)
                has_subfolders = any(c.is_folder == BooleanEnum.YES for c in children)

                # Construct FileEntity
                full_path = await vfs.get_full_path(user_id, node.id)

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

    async def list_recycle(self, user: str) -> list[RecycleEntity]:
        """List files in recycle bin for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)

        recycle_files: list[RecycleEntity] = []

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            items = await vfs.list_recycle(user_id)

            for item in items:
                recycle_files.append(_to_recycle_entity(item))

        return recycle_files

    async def delete_from_recycle(self, user: str, id_list: list[int]) -> BaseResponse:
        """Permanently delete items from recycle bin for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            await vfs.purge_recycle(user_id, id_list)

        return BaseResponse()

    async def revert_from_recycle(self, user: str, id_list: list[int]) -> BaseResponse:
        """Restore items from recycle bin for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            for recycle_id in id_list:
                await vfs.restore_node(user_id, recycle_id)

        return BaseResponse()

    async def clear_recycle(self, user: str) -> BaseResponse:
        """Empty the recycle bin for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            await vfs.purge_recycle(user_id)

        return BaseResponse()

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

            for item in do_list:
                # Resolve full path using VFS recursion
                full_path = await vfs.get_full_path(user_id, item.id)
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

            # Mapping to FileEntity
            file_entities: list[FileEntity] = []
            for item in items:
                full_path = await vfs.get_full_path(user_id, item.id)
                file_entities.append(_to_file_entity(item, full_path))

            return file_entities
