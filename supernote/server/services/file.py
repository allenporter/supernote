import logging
import urllib.parse
from pathlib import Path
from typing import List

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
from .storage import StorageService
from .user import UserService
from .vfs import VirtualFileSystem

logger = logging.getLogger(__name__)


class FileService:
    """File service."""

    def __init__(
        self,
        storage_service: StorageService,
        user_service: UserService,
        session_manager: DatabaseSessionManager,
    ) -> None:
        """Initialize the file service."""
        self.storage_service = storage_service
        self.user_service = user_service
        self.session_manager = session_manager

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

            if recursive:
                recursive_list = await vfs.list_recursive(user_id, folder_id)
                for item, rel_path in recursive_list:
                    entries.append(
                        EntriesVO(
                            tag="folder" if item.is_folder == "Y" else "file",
                            id=str(item.id),
                            name=item.file_name,
                            path_display=f"/{rel_path}",  # Placeholder
                            parent_path="",  # Placeholder
                            content_hash=item.md5 or "",
                            is_downloadable=True,
                            size=item.size,
                            last_update_time=item.update_time,
                        )
                    )
            else:
                do_list = await vfs.list_directory(user_id, folder_id)
                for item in do_list:
                    entries.append(
                        EntriesVO(
                            tag="folder" if item.is_folder == "Y" else "file",
                            id=str(item.id),
                            name=item.file_name,
                            path_display=f"/{item.file_name}",  # Placeholder
                            parent_path="",
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

            # Construct fully qualified path?
            # We don't easily know parent path string without walking up.
            # For now, use the requested path_str if it resolved, or just /Name

            # Default
            path_display = f"/{node.file_name}"

            # If the input path_str was what resolved the node (i.e. not an integer ID lookup)
            # we should trust it as the path (ensure leading slash).
            # If path_str is numeric, we treated it as ID.
            if not clean_path.isdigit():
                # It was a path lookup. Use the path_str.
                path_display = path_str if path_str.startswith("/") else f"/{path_str}"

            return EntriesVO(
                tag="folder" if node.is_folder == "Y" else "file",
                id=str(node.id),
                name=node.file_name,
                path_display=path_display,
                parent_path=str(Path(path_display).parent),
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
        # We trust the client's MD5 if the blob exists.
        # This assumes merge_chunks already wrote it.
        if not await self.storage_service.blob_storage.exists(content_hash):
            # Fallback check: maybe it wasn't merged yet? Or legacy flow?
            # For now, we enforce BlobStorage flow.
            # Check if we have a legacy temp file?
            temp_path = self.storage_service.resolve_temp_path(user, filename)
            if temp_path.exists():
                # Legacy path: calc md5, write to blob, verify
                calc_md5 = self.storage_service.get_file_md5(temp_path)
                if calc_md5 != content_hash:
                    raise ValueError(
                        f"Hash mismatch: expected {content_hash}, got {calc_md5}"
                    )

                # Write to blob storage
                with open(temp_path, "rb") as f:
                    data = f.read()
                    await self.storage_service.write_blob(data)

                # Continue with content_hash
            else:
                raise FileNotFoundError(
                    f"Blob {content_hash} not found and no temp file."
                )

        # 3. Create Metadata in VFS
        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)

            # Resolve parent path ID
            # path_str example: "/Notes/foo.txt" (filename included usually in path_str? No)
            # path_str is usually the directory?
            # In handle_upload_finish, data.path is passed.
            # Client usually sends path="/Notes", filename="foo.txt".

            # Ensure parent directory exists
            clean_path = path_str.strip("/")
            parent_id = 0
            if clean_path:
                parent_id = await vfs.ensure_directory_path(user_id, clean_path)

            # Create file node
            # We assume size is 0 or needed?
            # We can get size from BlobStorage? but BlobStorage doesn't store size metadata easily
            # without reading.
            # Ideally client sends size. But we only have content_hash.
            # Let's read size from blob_storage (via path stat) or just 0 for now.
            # Optimization: BlobStorage could return size.
            # LocalBlobStorage: get_blob_path(hash).stat().st_size
            blob_size = (
                self.storage_service.blob_storage.get_blob_path(content_hash)
                .stat()
                .st_size
            )

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

    def _get_unique_path(self, user: str, rel_path: str) -> str:
        """Generate a unique path if the destination exists for a user."""
        dest_path = self.storage_service.resolve_path(user, rel_path)
        if not dest_path.exists():
            return rel_path

        path_obj = Path(rel_path)
        parent = path_obj.parent
        stem = path_obj.stem
        suffix = path_obj.suffix

        counter = 1
        while True:
            new_name = f"{stem}({counter}){suffix}"
            new_rel_path = str(parent / new_name) if parent != Path(".") else new_name
            if not self.storage_service.resolve_path(user, new_rel_path).exists():
                return new_rel_path
            counter += 1

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

        recycle_files: List[RecycleFileVO] = []

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
        results: List[EntriesVO] = []

        async with self.session_manager.session() as session:
            vfs = VirtualFileSystem(session)
            do_list = await vfs.search_files(user_id, keyword)

            for item in do_list:
                # Reconstructing full path is hard without parent pointers recursion.
                # For now, we return name as display or just "/...".
                # Ideally UserFileDO should store parent_id, so we can walk up?
                # Or we just don't return full path correctly if not expensive?
                # Test expects path?
                # For flat search results, maybe just /Name is okay? or we need full path.
                # VFS: We can resolve full path if we walk up parent_id until 0.

                # Simple path reconstruction (placeholder)
                path_display = f"/{item.file_name}"

                results.append(
                    EntriesVO(
                        tag="folder" if item.is_folder == "Y" else "file",
                        id=str(item.id),
                        name=item.file_name,
                        path_display=path_display,
                        parent_path="/",  # Unknown without walk
                        size=item.size,
                        last_update_time=item.update_time,
                        content_hash=item.md5 or "",
                        is_downloadable=True,  # default
                    )
                )

        return results
