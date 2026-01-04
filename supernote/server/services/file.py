import asyncio
import hashlib
import logging
import shutil
from collections.abc import AsyncGenerator, Awaitable, Callable
from pathlib import Path

import aiofiles

from supernote.models.base import BaseResponse, BooleanEnum, create_error_response
from supernote.models.file import (
    EntriesVO,
    FileSortOrder,
    FileSortSequence,
)
from supernote.models.file_device import (
    CreateFolderLocalVO,
    DeleteFolderLocalVO,
    FileCopyLocalVO,
    FileMoveLocalVO,
    FileUploadFinishLocalVO,
)
from supernote.models.file_web import (
    FileListQueryVO,
    FilePathQueryVO,
    FileUploadFinishDTO,
    FolderListQueryVO,
    FolderVO,
    RecycleFileListVO,
    RecycleFileVO,
    UserFileVO,
)
from supernote.server.constants import CATEGORY_CONTAINERS, IMMUTABLE_SYSTEM_DIRECTORIES

from ..db.models.file import UserFileDO
from ..db.session import DatabaseSessionManager
from .blob import BlobStorage
from .user import UserService
from .vfs import VirtualFileSystem

logger = logging.getLogger(__name__)


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
    ) -> list[EntriesVO]:
        """List files in a folder for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        entries: list[EntriesVO] = []

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
                    # Construct full path display
                    # rel_path is relative to parent_path (clean_path)
                    # path_str is e.g. "/Notes" or "/"
                    parent_clean = path_str.strip("/")
                    path_display = (
                        f"{parent_clean}/{rel_path}" if parent_clean else rel_path
                    )

                    entries.append(
                        EntriesVO(
                            tag="folder" if item.is_folder == "Y" else "file",
                            id=str(item.id),
                            name=item.file_name,
                            path_display=path_display,
                            parent_path=str(Path(path_display).parent),
                            content_hash=item.md5 or "",
                            is_downloadable=True,
                            size=item.size,
                            last_update_time=item.update_time,
                        )
                    )
            else:
                # Flat listing
                do_list = await vfs.list_directory(user_id, parent_id)

                for item in do_list:
                    # Construct path_display
                    # This is tricky without fully qualified path in DO.
                    # But we know the parent path is path_str.
                    # path_str is e.g. "/Notes". Item name "foo.txt". -> "/Notes/foo.txt".
                    parent_clean = path_str.strip("/")
                    path_display = (
                        f"{parent_clean}/{item.file_name}"
                        if parent_clean
                        else item.file_name
                    )

                    entries.append(
                        EntriesVO(
                            tag="folder" if item.is_folder == "Y" else "file",
                            id=str(item.id),
                            name=item.file_name,
                            path_display=path_display,
                            parent_path=path_str.strip("/"),
                            content_hash=item.md5 or "",
                            is_downloadable=True,
                            size=item.size,
                            last_update_time=item.update_time,
                        )
                    )
        return entries

    async def list_folder_by_id(
        self, user: str, folder_id: int, recursive: bool = False
    ) -> list[EntriesVO]:
        """List files in a folder by ID for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        entries: list[EntriesVO] = []

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

                    parent_path = str(Path(full_path).parent)
                    if parent_path == ".":
                        parent_path = ""

                    entries.append(
                        EntriesVO(
                            tag="folder" if item.is_folder == "Y" else "file",
                            id=str(item.id),
                            name=item.file_name,
                            path_display=full_path,
                            parent_path=parent_path,
                            content_hash=item.md5 or "",
                            is_downloadable=True,
                            size=item.size,
                            last_update_time=item.update_time,
                        )
                    )
            else:
                do_list = await vfs.list_directory(user_id, folder_id)
                for item in do_list:
                    base_path_clean = base_path_display.strip("/")
                    full_path = (
                        f"{base_path_clean}/{item.file_name}"
                        if base_path_clean
                        else item.file_name
                    )

                    # Parent is the folder we are listing
                    parent_path = base_path_clean

                    entries.append(
                        EntriesVO(
                            tag="folder" if item.is_folder == "Y" else "file",
                            id=str(item.id),
                            name=item.file_name,
                            path_display=full_path,
                            parent_path=parent_path,
                            content_hash=item.md5 or "",
                            is_downloadable=True,
                            size=item.size,
                            last_update_time=item.update_time,
                        )
                    )
        return entries

    async def get_file_info(self, user: str, path_str: str) -> EntriesVO | None:
        """Get file info by path or ID for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)

        # Handle Root
        clean_path = path_str.strip("/")
        if not clean_path and (path_str == "" or path_str == "/"):
            # Virtual root directory
            return EntriesVO(
                tag="folder",
                id="0",
                name="",
                path_display="",
                parent_path="",  # Logical parent of root is root? or empty
                size=0,
                last_update_time=0,
                content_hash="",
                is_downloadable=False,
            )

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            node = None

            # 1. Try ID if numeric and large enough to be an ID
            if clean_path.isdigit():
                id_val = int(clean_path)
                node = await vfs.get_node_by_id(user_id, id_val)

            # 2. If not found by ID, try path resolution
            if not node:
                node = await vfs.resolve_path(user_id, path_str)

            if not node:
                return None

            # Always resolve the canonical path from the node structure
            path_display = await vfs.get_full_path(user_id, node.id)

            parent_path = str(Path(path_display).parent)
            if parent_path == ".":
                parent_path = ""

            return EntriesVO(
                tag="folder" if node.is_folder == "Y" else "file",
                id=str(node.id),
                name=node.file_name,
                path_display=path_display,
                parent_path=parent_path,
                content_hash=node.md5 or "",
                is_downloadable=True,
                size=node.size,
                last_update_time=node.update_time,
            )

    def _flatten_path(self, path: str) -> str:
        """Flatten paths for items inside category containers (e.g., NOTE/Note -> Note)."""

        path_parts = path.strip("/").split("/")
        if len(path_parts) >= 2 and path_parts[0] in CATEGORY_CONTAINERS:
            # Convert NOTE/Note/Sub -> Note/Sub
            return "/".join(path_parts[1:])
        return path

    async def get_path_info(
        self, user: str, node_id: int, flatten: bool = False
    ) -> FilePathQueryVO:
        """Resolve both full path and ID path for a node.
        
        Rules:
        - Both path and idPath end with a trailing slash (/).
        - idPath includes the terminal item ID.
        - idPath does NOT start with the root ID (0/).
        - If flatten=True, category containers are stripped from both.
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

            # Apply flattening if requested for Web API
            if flatten:
                from supernote.server.constants import CATEGORY_CONTAINERS

                if path_parts and path_parts[0] in CATEGORY_CONTAINERS:
                    path_parts = path_parts[1:]
                    id_path_parts = id_path_parts[1:]

            # Construct strings and append trailing slashes
            path = "/".join(path_parts)
            if path:
                path += "/"

            id_path = "/".join(id_path_parts)
            if id_path:
                id_path += "/"

            return FilePathQueryVO(path=path, id_path=id_path)

    async def finish_upload(
        self,
        user: str,
        filename: str,
        path_str: str,
        content_hash: str,
        equipment_no: str,
    ) -> FileUploadFinishLocalVO:
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

            file_id = str(new_file.id)

        # 4. Construct response
        clean_path = path_str.strip("/")
        full_path = f"{clean_path}/{filename}" if clean_path else filename

        return FileUploadFinishLocalVO(
            equipment_no=equipment_no,
            path_display=full_path,
            id=file_id,
            size=blob_size,
            name=filename,
            content_hash=content_hash,
        )

    async def upload_finish_web(
        self, user: str, dto: FileUploadFinishDTO
    ) -> BaseResponse:
        """Finish upload (Web API)."""
        user_id = await self.user_service.get_user_id(user)

        # 1. Check/Promote Blob
        # Note: We use inner_name to find the temp file if not in blob storage
        if not await self.blob_storage.exists(dto.md5):
            temp_path = self.resolve_temp_path(user, dto.inner_name)
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

                if calc_md5 != dto.md5:
                    raise ValueError(
                        f"Hash mismatch: expected {dto.md5}, got {calc_md5}"
                    )

                # Promote to Blob
                async with aiofiles.open(temp_path, "rb") as f:
                    data = await f.read()
                    await self.blob_storage.write_blob(data)

                await asyncio.to_thread(temp_path.unlink, missing_ok=True)
            else:
                # If neither blob nor temp file exists -> error
                raise FileNotFoundError(
                    f"Blob {dto.md5} not found and temporary file {dto.inner_name} missing."
                )

        # 2. Create VFS Node
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            # Verify directory exists? (Optional, create_file might check FK or fail)
            # create_file expects valid parent_id.

            # Using actual size from blob or DTO? DTO usually trusted or verified during promotion.
            # Ideally verify blob size.
            blob_size = self.blob_storage.get_blob_path(dto.md5).stat().st_size

            await vfs.create_file(
                user_id=user_id,
                parent_id=dto.directory_id,
                name=dto.file_name,
                size=blob_size,
                md5=dto.md5,
            )

        return BaseResponse()

    async def create_directory(
        self, user: str, path: str, equipment_no: str
    ) -> CreateFolderLocalVO:
        """Create a directory for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        rel_path = path.lstrip("/")

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            if rel_path:
                await vfs.ensure_directory_path(user_id, rel_path)

        return CreateFolderLocalVO(equipment_no=equipment_no)

    # TODO: We should be able to share code between the version that creates by path
    # and the version that creates by ID.
    async def create_directory_by_id(
        self, user: str, parent_id: int, name: str
    ) -> FolderVO:
        """Create a directory by parent ID for a specific user."""
        user_id = await self.user_service.get_user_id(user)
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            # TODO: This is not checking if the existing directory is empty
            # or not. Its returning an existing id and we can't tell the difference.
            new_dir = await vfs.create_directory(user_id, parent_id, name)

            return FolderVO(
                id=str(new_dir.id),
                directory_id=str(new_dir.directory_id),
                file_name=new_dir.file_name,
                empty=BooleanEnum.YES,  # Newly created is empty
            )

    async def delete_item(
        self, user: str, id: int, equipment_no: str
    ) -> DeleteFolderLocalVO:
        """Delete a file or directory for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)

            # Immutability check
            node = await vfs.get_node_by_id(user_id, id)
            if node and node.file_name in IMMUTABLE_SYSTEM_DIRECTORIES:
                return DeleteFolderLocalVO(
                    equipment_no=equipment_no,
                    success=False,
                    error_msg=f"Cannot delete system directory: {node.file_name}",
                    error_code="E_SYSTEM_DIR",
                )

            success = await vfs.delete_node(user_id, id)
            if not success:
                logger.warning(f"Delete requested for unknown ID: {id} for user {user}")

        return DeleteFolderLocalVO(equipment_no=equipment_no)

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
                    return create_error_response(
                        f"Cannot delete system directory: {node.file_name}",
                        "E_SYSTEM_DIR",
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
        source_parent_id: int,
        target_parent_id: int,
    ) -> BaseResponse:
        """Batch move items for a specific user."""
        user_id = await self.user_service.get_user_id(user)

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            for item_id in id_list:
                node = await vfs.get_node_by_id(user_id, item_id)
                if not node:
                    continue

                if node.directory_id != source_parent_id:
                    # Special case for flattened Web API: allow source_parent_id=0 if it's a categorized folder
                    from supernote.server.constants import CATEGORY_CONTAINERS

                    is_categorized = False
                    async with self.session_manager.session() as sess:
                        vfs_i = VirtualFileSystem(sess)
                        p_node = await vfs_i.get_node_by_id(user_id, node.directory_id)
                        if p_node and p_node.file_name in CATEGORY_CONTAINERS:
                            is_categorized = True

                    if not (source_parent_id == 0 and is_categorized):
                        return create_error_response(
                            f"Item {item_id} is not in directory {source_parent_id}",
                            "E400",
                        )

                # Immutability check
                if node.file_name in IMMUTABLE_SYSTEM_DIRECTORIES:
                    return create_error_response(
                        f"Cannot move system directory: {node.file_name}",
                        "E_SYSTEM_DIR",
                    )

                await vfs.move_node(user_id, item_id, target_parent_id, node.file_name)

        return BaseResponse(success=True)

    async def move_item(
        self, user: str, id: int, to_path: str, autorename: bool, equipment_no: str
    ) -> FileMoveLocalVO:
        """Move a file or directory for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            node = await vfs.get_node_by_id(user_id, id)
            if not node:
                raise FileNotFoundError("Source not found")

            # Immutability check
            if node.file_name in IMMUTABLE_SYSTEM_DIRECTORIES:
                raise ValueError(f"Cannot move system directory: {node.file_name}")

            # Resolve destination parent
            clean_to_path = to_path.strip("/")
            parent_id = 0
            if clean_to_path:
                parent_id = await vfs.ensure_directory_path(user_id, clean_to_path)

            # Autorename logic
            # Simplified: if conflict, append (1)
            # This logic should ideally be in VFS move_node or handled here by checking existence.
            # For now, let's assume move_node returns success.
            # If we need autorename, we need to check if name exists in parent_id.

            new_name = node.file_name
            # TODO: Implement full autorename logic using VFS existence checks?
            # For MVP/Lite, we might just try moving.

            await vfs.move_node(user_id, id, parent_id, new_name)

        return FileMoveLocalVO(equipment_no=equipment_no)

    async def copy_items(
        self,
        user: str,
        id_list: list[int],
        source_parent_id: int,
        target_parent_id: int,
    ) -> BaseResponse:
        """Batch copy items for a specific user."""
        user_id = await self.user_service.get_user_id(user)

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            for item_id in id_list:
                node = await vfs.get_node_by_id(user_id, item_id)
                if not node:
                    continue

                # Check immutability? Usually copy is allowed, but let's be safe.
                # Actually device API copy_item blocks it too.
                if node.file_name in IMMUTABLE_SYSTEM_DIRECTORIES:
                    return create_error_response(
                        f"Cannot copy system directory: {node.file_name}",
                        "E_SYSTEM_DIR",
                    )

                # Copy logic (no source parent check usually required for copy but we can add it for completeness)
                await vfs.copy_node(user_id, item_id, target_parent_id, node.file_name)

        return BaseResponse(success=True)

    async def copy_item(
        self, user: str, id: int, to_path: str, autorename: bool, equipment_no: str
    ) -> FileCopyLocalVO:
        """Copy a file or directory for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            node = await vfs.get_node_by_id(user_id, id)
            if not node:
                raise FileNotFoundError("Source not found")

            # Immutability check
            if node.file_name in IMMUTABLE_SYSTEM_DIRECTORIES:
                raise ValueError(f"Cannot copy system directory: {node.file_name}")

            # Resolve destination parent
            clean_to_path = to_path.strip("/")
            parent_id = 0
            if clean_to_path:
                parent_id = await vfs.ensure_directory_path(user_id, clean_to_path)

            # Autorename Logic
            new_name = node.file_name
            if autorename:
                base_name = new_name
                ext = ""
                if "." in base_name and not node.is_folder == "Y":
                    parts = base_name.rsplit(".", 1)
                    base_name = parts[0]
                    ext = f".{parts[1]}"

                counter = 1
                while True:
                    # Check if exists
                    exists = await vfs._check_exists(
                        user_id, parent_id, new_name, node.is_folder
                    )
                    if not exists:
                        break
                    new_name = f"{base_name}({counter}){ext}"
                    counter += 1

            await vfs.copy_node(user_id, id, parent_id, new_name)

        return FileCopyLocalVO(equipment_no=equipment_no)

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
            await vfs.move_node(user_id, id, node.directory_id, new_name)

        return BaseResponse(success=True)

    async def get_folders_by_ids(
        self, user: str, parent_id: int, id_list: list[int]
    ) -> FolderListQueryVO:
        """Get details for a list of folders."""
        user_id = await self.user_service.get_user_id(user)
        folder_vos: list[FolderVO] = []

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            for folder_id in id_list:
                node = await vfs.get_node_by_id(user_id, folder_id)
                if node and node.is_folder == "Y":
                    # Check if empty
                    children = await vfs.list_directory(user_id, folder_id)
                    folder_vos.append(
                        FolderVO(
                            id=str(node.id),
                            directory_id=str(node.directory_id),
                            file_name=node.file_name,
                            empty=BooleanEnum.YES if not children else BooleanEnum.NO,
                        )
                    )

        return FolderListQueryVO(folder_vo_list=folder_vos)

    async def list_recycle(
        self, user: str, order: str, sequence: str, page_no: int, page_size: int
    ) -> RecycleFileListVO:
        """List files in recycle bin for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)

        recycle_files: list[RecycleFileVO] = []

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            items = await vfs.list_recycle(user_id)

            for item in items:
                recycle_files.append(
                    RecycleFileVO(
                        file_id=str(
                            item.id
                        ),  # Recycle ID, not Original File ID? Client usually wants ID to action on.
                        # Wait, legacy physical implementation returned "trash_rel_path" ID.
                        # Here we have RecycleFileDO.id.
                        # But revert uses this ID.
                        is_folder=item.is_folder,
                        file_name=item.file_name,
                        size=item.size,
                        update_time=str(item.delete_time),
                    )
                )

        # Sort
        if order == "filename":
            recycle_files.sort(key=lambda x: x.file_name, reverse=(sequence == "desc"))
        elif order == "size":
            recycle_files.sort(key=lambda x: x.size, reverse=(sequence == "desc"))
        else:  # time
            recycle_files.sort(
                key=lambda x: x.update_time, reverse=(sequence == "desc")
            )

        # Paginate
        total = len(recycle_files)
        start = (page_no - 1) * page_size
        end = start + page_size
        page_items = recycle_files[start:end]

        return RecycleFileListVO(total=total, recycle_file_vo_list=page_items)

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

    async def search_files(
        self, user: str, keyword: str, flatten: bool = False
    ) -> list[EntriesVO]:
        """Search for files matching the keyword in user's storage.

        Args:
            user: User email.
            keyword: Search keyword.
            flatten: If True, flattens paths of system folders in category containers (Web API view).
        """
        user_id = await self.user_service.get_user_id(user)
        results: list[EntriesVO] = []

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            do_list = await vfs.search_files(user_id, keyword)

            for item in do_list:
                # Resolve full path using VFS recursion
                path_display = await vfs.get_full_path(user_id, item.id)

                if flatten:
                    path_display = self._flatten_path(path_display)

                parent_path = str(Path(path_display).parent)
                if parent_path == ".":
                    parent_path = ""

                results.append(
                    EntriesVO(
                        tag="folder" if item.is_folder == "Y" else "file",
                        id=str(item.id),
                        name=item.file_name,
                        path_display=path_display,
                        parent_path=parent_path,
                        size=item.size,
                        last_update_time=item.update_time,
                        content_hash=item.md5 or "",
                        is_downloadable=True,  # default
                    )
                )

        return results

    async def query_file_list(
        self,
        user: str,
        directory_id: int,
        order: str,
        sequence: str,
        page_no: int,
        page_size: int,
    ) -> FileListQueryVO:
        """Query files in a directory for a specific user."""
        user_id = await self.user_service.get_user_id(user)

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            items = await vfs.list_directory(user_id, directory_id)

        # Flatten directory structure ONLY for root listing (web API behavior)
        if directory_id == 0:
            items = await self._flatten_root_directory(user_id, items)

        # Mapping
        user_file_vos: list[UserFileVO] = []
        for item in items:
            user_file_vos.append(
                UserFileVO(
                    id=str(item.id),
                    directory_id=str(item.directory_id),
                    file_name=item.file_name,
                    size=item.size,
                    md5=item.md5,
                    inner_name=item.md5,
                    is_folder=BooleanEnum.YES
                    if item.is_folder == "Y"
                    else BooleanEnum.NO,
                    create_time=item.create_time,
                    update_time=item.update_time,
                )
            )

        # Sorting
        reverse = sequence.lower() == FileSortSequence.DESC
        if order == FileSortOrder.FILENAME:
            user_file_vos.sort(key=lambda x: x.file_name, reverse=reverse)
        elif order == FileSortOrder.TIME:
            user_file_vos.sort(key=lambda x: x.update_time or 0, reverse=reverse)
        elif order == FileSortOrder.SIZE:
            user_file_vos.sort(key=lambda x: x.size or 0, reverse=reverse)

        # Pagination
        total = len(user_file_vos)
        start = (page_no - 1) * page_size
        end = start + page_size
        page_items = user_file_vos[start:end]

        pages = max(1, (total + page_size - 1) // page_size)

        return FileListQueryVO(
            total=total,
            pages=pages,
            page_num=page_no,
            page_size=page_size,
            user_file_vo_list=page_items,
        )

    async def _flatten_root_directory(
        self, user_id: int, items: list[UserFileDO]
    ) -> list[UserFileDO]:
        """Flatten categorized folders to appear at root level (web API only).

        Transforms:
            NOTE/ (hidden)
            NOTE/Note → Note (directoryId=0)
            NOTE/MyStyle → MyStyle (directoryId=0)
            DOCUMENT/ (hidden)
            DOCUMENT/Document → Document (directoryId=0)
        """
        # Category containers to flatten
        CATEGORY_FOLDERS = {"NOTE", "DOCUMENT"}

        # Find category parent IDs
        parent_map = {
            item.id: item.file_name
            for item in items
            if item.file_name in CATEGORY_FOLDERS
        }

        if not parent_map:
            return items  # No flattening needed

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            flattened = []

            # Keep system folders (Export, Inbox, Screenshot) and others not in categories
            for item in items:
                if item.file_name not in CATEGORY_FOLDERS:
                    flattened.append(item)

            # Add children of category folders, modified to appear at root
            for parent_id in parent_map.keys():
                children = await vfs.list_directory(user_id, parent_id)
                for child in children:
                    # Clone and modify directory_id to 0 for web API view
                    # We don't modify the actual DO we got from DB, just the list we return
                    # Actually, SQLAlchemy might track these if we just modify them.
                    # Let's create shallow copies of the DO specifically for the VO mapping.
                    child_copy = UserFileDO(
                        id=child.id,
                        user_id=child.user_id,
                        directory_id=0,  # Flattened to root
                        file_name=child.file_name,
                        size=child.size,
                        md5=child.md5,
                        is_folder=child.is_folder,
                        is_active=child.is_active,
                        create_time=child.create_time,
                        update_time=child.update_time,
                    )
                    flattened.append(child_copy)

        return flattened
