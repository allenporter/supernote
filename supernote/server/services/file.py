import logging
import urllib.parse
from pathlib import Path
from typing import List, Optional

from ..models.file import FileEntryVO, UploadApplyResponse, UploadFinishResponse
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

                entries.append(
                    FileEntryVO(
                        tag="folder" if is_dir else "file",
                        id=f"{path_str.rstrip('/')}/{entry.name}".lstrip("/"),
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

        return FileEntryVO(
            tag="folder" if target_path.is_dir() else "file",
            id=rel_path,
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

        return UploadFinishResponse(
            equipment_no=equipment_no,
            path_display=f"{path_str.rstrip('/')}/{filename}",
            id=f"{path_str.rstrip('/')}/{filename}".lstrip("/"),
            size=dest_path.stat().st_size,
            name=filename,
            content_hash=calculated_hash,
        )
