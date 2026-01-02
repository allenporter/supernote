import asyncio
import hashlib
import logging
import shutil
import urllib.parse
from collections.abc import AsyncGenerator, Awaitable, Callable
from pathlib import Path

import aiofiles

from supernote.models.base import BaseResponse
from supernote.models.file import (
    CreateFolderLocalVO,
    DeleteFolderLocalVO,
    EntriesVO,
    FileCopyLocalVO,
    FileMoveLocalVO,
    FileUploadApplyLocalVO,
    FileUploadFinishLocalVO,
    RecycleFileListVO,
    RecycleFileVO,
)

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
                    parent_clean = path_str.rstrip("/")
                    path_display = f"{parent_clean}/{rel_path}"
                    if not parent_clean:
                        path_display = f"/{rel_path}"

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
                    parent_clean = path_str.rstrip("/")
                    path_display = f"{parent_clean}/{item.file_name}"
                    if not parent_clean:
                        path_display = f"/{item.file_name}"

                    entries.append(
                        EntriesVO(
                            tag="folder" if item.is_folder == "Y" else "file",
                            id=str(item.id),
                            name=item.file_name,
                            path_display=path_display,
                            parent_path=path_str
                            if path_str.startswith("/")
                            else "/" + path_str,
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
                    if base_path_display == "" or base_path_display == "/":
                        full_path = f"/{rel_path}"
                    else:
                        full_path = f"{base_path_display}/{rel_path}"

                    parent_path = str(Path(full_path).parent)
                    if parent_path == ".":
                        parent_path = "/"

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
                    if base_path_display == "" or base_path_display == "/":
                        full_path = f"/{item.file_name}"
                    else:
                        full_path = f"{base_path_display}/{item.file_name}"

                    # Parent is the folder we are listing
                    parent_path = base_path_display if base_path_display else "/"

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
                path_display="/",
                parent_path="/",  # Logical parent of root is root? or empty
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
                parent_path = "/"

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

    def apply_upload(
        self, user: str, file_name: str, equipment_no: str, host: str
    ) -> FileUploadApplyLocalVO:
        """Apply for upload by a specific user."""
        # Note: Ideally, the upload URL should also contain user context if it's handled by a separate request
        # But handle_upload_data currently might need to extract user from JWT or filename.
        # Since we use filename in the URL, and handle_upload_data will extract user from request["user"].
        encoded_name = urllib.parse.quote(file_name)
        upload_url = f"http://{host}/api/file/upload/data/{encoded_name}"

        return FileUploadApplyLocalVO(
            equipment_no=equipment_no,
            bucket_name="supernote-local",
            inner_name=file_name,
            x_amz_date="",
            authorization="",
            full_upload_url=upload_url,
            part_upload_url=upload_url,
        )

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
            if temp_path.exists():
                # Calculate MD5 and promote to blob
                hash_md5 = hashlib.md5()
                with open(temp_path, "rb") as f:
                    for chunk in iter(lambda: f.read(4096), b""):
                        hash_md5.update(chunk)
                calc_md5 = hash_md5.hexdigest()

                if calc_md5 != content_hash:
                    raise ValueError(
                        f"Hash mismatch: expected {content_hash}, got {calc_md5}"
                    )

                # Write to blob
                with open(temp_path, "rb") as f:
                    data = f.read()
                    await self.blob_storage.write_blob(data)

                # Cleanup temp
                temp_path.unlink(missing_ok=True)
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
        full_path = f"{path_str.rstrip('/')}/{filename}"
        if not path_str or path_str == "/":
            full_path = f"/{filename}"

        return FileUploadFinishLocalVO(
            equipment_no=equipment_no,
            path_display=full_path,
            id=file_id,
            size=blob_size,
            name=filename,
            content_hash=content_hash,
        )

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

    async def delete_item(
        self, user: str, id: int, equipment_no: str
    ) -> DeleteFolderLocalVO:
        """Delete a file or directory for a specific user using VFS."""
        user_id = await self.user_service.get_user_id(user)
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            success = await vfs.delete_node(user_id, id)
            if not success:
                logger.warning(f"Delete requested for unknown ID: {id} for user {user}")

        return DeleteFolderLocalVO(equipment_no=equipment_no)

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
    ) -> int:
        """Save data to user's temp file."""
        temp_path = self.resolve_temp_path(user, filename)
        temp_path.parent.mkdir(parents=True, exist_ok=True)

        loop = asyncio.get_running_loop()
        f = await loop.run_in_executor(None, open, temp_path, "wb")
        total_bytes = 0
        try:
            while True:
                chunk = await chunk_reader()
                if not chunk:
                    break
                await loop.run_in_executor(None, f.write, chunk)
                total_bytes += len(chunk)
        finally:
            await loop.run_in_executor(None, f.close)
        return total_bytes

    async def save_chunk_file(
        self,
        user: str,
        upload_id: str,
        filename: str,
        part_number: int,
        chunk_reader: Callable[[], Awaitable[bytes]],
    ) -> int:
        """Save a single chunk."""
        chunk_path = self.get_chunk_path(user, upload_id, filename, part_number)
        chunk_path.parent.mkdir(parents=True, exist_ok=True)

        loop = asyncio.get_running_loop()
        f = await loop.run_in_executor(None, open, chunk_path, "wb")
        total_bytes = 0
        try:
            while True:
                chunk = await chunk_reader()
                if not chunk:
                    break
                await loop.run_in_executor(None, f.write, chunk)
                total_bytes += len(chunk)
        finally:
            await loop.run_in_executor(None, f.close)

        logger.info(
            f"Saved chunk {part_number} for {filename} (user: {user}): {total_bytes} bytes"
        )
        return total_bytes

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

    async def search_files(self, user: str, keyword: str) -> list[EntriesVO]:
        """Search for files matching the keyword in user's storage."""
        user_id = await self.user_service.get_user_id(user)
        results: list[EntriesVO] = []

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            do_list = await vfs.search_files(user_id, keyword)

            for item in do_list:
                # Resolve full path using VFS recursion
                path_display = await vfs.get_full_path(user_id, item.id)
                parent_path = str(Path(path_display).parent)
                if parent_path == ".":
                    parent_path = "/"

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
