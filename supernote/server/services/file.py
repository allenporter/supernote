import logging
import urllib.parse
from pathlib import Path
from typing import List, Optional

from ..models.base import BaseResponse
from ..models.file import (
    CreateDirectoryResponse,
    DeleteResponse,
    FileCopyResponse,
    FileEntryVO,
    FileMoveResponse,
    RecycleFileListResponse,
    RecycleFileVO,
    UploadApplyResponse,
    UploadFinishResponse,
)
from .storage import StorageService

logger = logging.getLogger(__name__)


class FileService:
    def __init__(self, storage_service: StorageService):
        self.storage_service = storage_service

    def list_folder(self, path_str: str) -> List[FileEntryVO]:
        """List files in a folder."""
        rel_path = path_str.lstrip("/")
        entries = []

        try:
            for entry in self.storage_service.list_directory(rel_path):
                is_dir = entry.is_dir()
                stat = entry.stat()

                content_hash = ""
                if not is_dir:
                    content_hash = self.storage_service.get_file_md5(Path(entry.path))

                # ID generation
                if is_dir:
                    entry_rel_path = f"{rel_path}/{entry.name}".strip("/")
                else:
                    entry_rel_path = f"{rel_path}/{entry.name}".strip("/")

                file_id = str(self.storage_service.get_id_from_path(entry_rel_path))

                entries.append(
                    FileEntryVO(
                        tag="folder" if is_dir else "file",
                        id=file_id,
                        name=entry.name,
                        path_display=f"{path_str.rstrip('/')}/{entry.name}",
                        parent_path=path_str,
                        content_hash=content_hash,
                        is_downloadable=True,
                        size=stat.st_size,
                        last_update_time=int(stat.st_mtime * 1000),
                    )
                )
        except FileNotFoundError:
            pass

        return entries

    def get_file_info(self, path_str: str) -> Optional[FileEntryVO]:
        """Get file info by path."""
        rel_path = path_str.lstrip("/")
        target_path = self.storage_service.resolve_path(rel_path)

        if not target_path.exists():
            return None

        stat = target_path.stat()
        content_hash = ""
        if not target_path.is_dir():
            content_hash = self.storage_service.get_file_md5(target_path)

        # Reconstruct display path if needed, but here we assume path_str is the display path
        # unless it's an ID (relative path)
        path_display = path_str
        if not path_str.startswith("/"):
            path_display = "/" + path_str

        file_id = str(self.storage_service.get_id_from_path(rel_path))

        return FileEntryVO(
            tag="folder" if target_path.is_dir() else "file",
            id=file_id,
            name=target_path.name,
            path_display=path_display,
            parent_path=str(Path(path_display).parent),
            content_hash=content_hash,
            is_downloadable=True,
            size=stat.st_size,
            last_update_time=int(stat.st_mtime * 1000),
        )

    def apply_upload(
        self, file_name: str, equipment_no: str, host: str
    ) -> UploadApplyResponse:
        """Apply for upload."""
        encoded_name = urllib.parse.quote(file_name)
        upload_url = f"http://{host}/api/file/upload/data/{encoded_name}"

        return UploadApplyResponse(
            equipment_no=equipment_no,
            bucket_name="supernote-local",
            inner_name=file_name,
            x_amz_date="",
            authorization="",
            full_upload_url=upload_url,
            part_upload_url=upload_url,
        )

    def finish_upload(
        self, filename: str, path_str: str, content_hash: str, equipment_no: str
    ) -> UploadFinishResponse:
        """Finish upload."""
        rel_path = path_str.lstrip("/")
        temp_path = self.storage_service.resolve_temp_path(filename)

        if not temp_path.exists():
            raise FileNotFoundError("Upload not found")

        # Verify MD5
        calculated_hash = self.storage_service.get_file_md5(temp_path)
        if calculated_hash != content_hash:
            logger.warning(
                f"Hash mismatch for {filename}: expected {content_hash}, got {calculated_hash}"
            )

        dest_path = self.storage_service.move_temp_to_storage(filename, rel_path)

        final_rel_path = f"{path_str.rstrip('/')}/{filename}".lstrip("/")
        file_id = str(self.storage_service.get_id_from_path(final_rel_path))

        return UploadFinishResponse(
            equipment_no=equipment_no,
            path_display=f"{path_str.rstrip('/')}/{filename}",
            id=file_id,
            size=dest_path.stat().st_size,
            name=filename,
            content_hash=calculated_hash,
        )

    def create_directory(self, path: str, equipment_no: str) -> CreateDirectoryResponse:
        """Create a directory."""
        rel_path = path.lstrip("/")
        self.storage_service.create_directory(rel_path)
        return CreateDirectoryResponse(equipment_no=equipment_no)

    def delete_item(self, id: int, equipment_no: str) -> DeleteResponse:
        """Delete a file or directory (soft delete to recycle bin)."""
        rel_path = self.storage_service.get_path_from_id(id)
        if rel_path:
            self.storage_service.soft_delete(rel_path)
        else:
            logger.warning(f"Delete requested for unknown ID: {id}")

        return DeleteResponse(equipment_no=equipment_no)

    def _get_unique_path(self, rel_path: str) -> str:
        """Generate a unique path if the destination exists."""
        dest_path = self.storage_service.resolve_path(rel_path)
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
            if not self.storage_service.resolve_path(new_rel_path).exists():
                return new_rel_path
            counter += 1

    def move_item(
        self, id: int, to_path: str, autorename: bool, equipment_no: str
    ) -> FileMoveResponse:
        """Move a file or directory."""
        rel_src_path = self.storage_service.get_path_from_id(id)
        if not rel_src_path:
            raise FileNotFoundError("Source not found")

        src_name = Path(rel_src_path).name
        # to_path is the target directory
        clean_to_path = to_path.strip("/")
        if clean_to_path:
            rel_dest_path = f"{clean_to_path}/{src_name}"
        else:
            rel_dest_path = src_name

        if autorename:
            rel_dest_path = self._get_unique_path(rel_dest_path)

        self.storage_service.move_path(rel_src_path, rel_dest_path)
        return FileMoveResponse(equipment_no=equipment_no)

    def copy_item(
        self, id: int, to_path: str, autorename: bool, equipment_no: str
    ) -> FileCopyResponse:
        """Copy a file or directory."""
        rel_src_path = self.storage_service.get_path_from_id(id)
        if not rel_src_path:
            raise FileNotFoundError("Source not found")

        src_name = Path(rel_src_path).name
        clean_to_path = to_path.strip("/")
        if clean_to_path:
            rel_dest_path = f"{clean_to_path}/{src_name}"
        else:
            rel_dest_path = src_name

        if autorename:
            rel_dest_path = self._get_unique_path(rel_dest_path)

        self.storage_service.copy_path(rel_src_path, rel_dest_path)
        return FileCopyResponse(equipment_no=equipment_no)

    def list_recycle(
        self, order: str, sequence: str, page_no: int, page_size: int
    ) -> RecycleFileListResponse:
        """List files in recycle bin."""

        items = self.storage_service.list_trash()

        # Convert to RecycleFileVO
        recycle_files = []
        for trash_path, timestamp in items:
            # Extract original name from trash name (timestamp_originalname)
            original_name = "_".join(trash_path.name.split("_")[1:])
            is_folder = "Y" if trash_path.is_dir() else "N"
            size = 0
            if trash_path.is_file():
                size = trash_path.stat().st_size

            # Generate ID from trash path
            trash_rel_path = f".trash/{trash_path.name}"
            file_id = str(self.storage_service.get_id_from_path(trash_rel_path))

            recycle_files.append(
                RecycleFileVO(
                    file_id=file_id,
                    is_folder=is_folder,
                    file_name=original_name,
                    size=size,
                    update_time=timestamp,
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

        return RecycleFileListResponse(total=total, recycle_file_vo_list=page_items)

    def delete_from_recycle(self, id_list: list[int]) -> BaseResponse:
        """Permanently delete items from recycle bin."""
        for file_id in id_list:
            # Find trash path by ID
            trash_rel_path = self.storage_service.get_path_from_id(file_id)
            if trash_rel_path and trash_rel_path.startswith(".trash/"):
                self.storage_service.delete_from_trash(trash_rel_path)

        return BaseResponse()

    def revert_from_recycle(self, id_list: list[int]) -> BaseResponse:
        """Restore items from recycle bin."""
        for file_id in id_list:
            # Find trash path by ID
            trash_rel_path = self.storage_service.get_path_from_id(file_id)
            if trash_rel_path and trash_rel_path.startswith(".trash/"):
                # Extract original name from trash name
                trash_name = Path(trash_rel_path).name
                original_name = "_".join(trash_name.split("_")[1:])

                # Restore to root for now (could be enhanced to remember original location)
                self.storage_service.restore_from_trash(trash_rel_path, original_name)

        return BaseResponse()

    def clear_recycle(self) -> BaseResponse:
        """Empty the recycle bin."""
        self.storage_service.empty_trash()
        return BaseResponse()

    def search_files(self, keyword: str) -> list[FileEntryVO]:
        """Search for files matching the keyword.

        Args:
            keyword: Search keyword (case-insensitive)

        Returns:
            List of matching FileEntryVO objects
        """

        results = []
        keyword_lower = keyword.lower()

        # Walk the entire storage directory
        for root_path in self.storage_service.storage_root.rglob("*"):
            # Skip hidden files/dirs and temp
            if any(part.startswith(".") for part in root_path.parts):
                continue
            if "temp" in root_path.parts:
                continue

            # Check if filename matches keyword
            if keyword_lower in root_path.name.lower():
                # Get relative path
                try:
                    rel_path = str(
                        root_path.relative_to(self.storage_service.storage_root)
                    )
                except ValueError:
                    continue

                # Generate ID
                file_id = str(self.storage_service.get_id_from_path(rel_path))

                # Determine tag (folder or file)
                tag = "folder" if root_path.is_dir() else "file"

                # Get size
                size = 0
                if root_path.is_file():
                    size = root_path.stat().st_size

                # Get modification time
                mod_time = int(root_path.stat().st_mtime * 1000)  # milliseconds

                # Get parent path
                parent_path = (
                    str(Path(rel_path).parent)
                    if Path(rel_path).parent != Path(".")
                    else "/"
                )

                results.append(
                    FileEntryVO(
                        tag=tag,
                        id=file_id,
                        name=root_path.name,
                        path_display=f"/{rel_path}",
                        parent_path=parent_path,
                        size=size,
                        last_update_time=mod_time,
                    )
                )

        return results
