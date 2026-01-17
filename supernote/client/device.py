import hashlib
import logging
from pathlib import Path

from supernote.models.file_common import FileUploadApplyLocalVO
from supernote.models.file_device import (
    CapacityLocalDTO,
    CapacityLocalVO,
    CreateFolderLocalDTO,
    CreateFolderLocalVO,
    DeleteFolderLocalDTO,
    DeleteFolderLocalVO,
    FileCopyLocalDTO,
    FileCopyLocalVO,
    FileDownloadLocalDTO,
    FileDownloadLocalVO,
    FileMoveLocalDTO,
    FileMoveLocalVO,
    FileQueryByPathLocalDTO,
    FileQueryByPathLocalVO,
    FileQueryLocalDTO,
    FileQueryLocalVO,
    FileUploadApplyLocalDTO,
    FileUploadFinishLocalDTO,
    FileUploadFinishLocalVO,
    ListFolderLocalDTO,
    ListFolderLocalVO,
    ListFolderV2DTO,
    PdfDTO,
    PdfVO,
    PngDTO,
    PngVO,
    SynchronousEndLocalDTO,
    SynchronousEndLocalVO,
    SynchronousStartLocalDTO,
    SynchronousStartLocalVO,
)

from .client import Client

_LOGGER = logging.getLogger(__name__)


class DeviceClient:
    """Client for Device (V2/V3) APIs."""

    def __init__(self, client: Client) -> None:
        """Initialize the DeviceClient."""
        self._client = client

    async def create_folder(
        self, path: str, equipment_no: str, autorename: bool = False
    ) -> CreateFolderLocalVO:
        """Create a folder (V2)."""
        dto = CreateFolderLocalDTO(
            path=path, equipment_no=equipment_no, autorename=autorename
        )
        return await self._client.post_json(
            "/api/file/2/files/create_folder_v2",
            CreateFolderLocalVO,
            json=dto.to_dict(),
        )

    async def list_folder(
        self,
        path: str | None = None,
        folder_id: int | None = None,
        equipment_no: str | None = None,
        recursive: bool = False,
    ) -> ListFolderLocalVO:
        """List folder contents.

        This supports both V2 and V3 APIs. You can either specify path or folder_id.

        Args:
            path: Path to list contents of.
            folder_id: ID of folder to list contents of.
            equipment_no: Equipment number.
            recursive: Whether to list recursively.

        Returns:
            ListFolderLocalVO
        """
        if path is not None:
            dto_v2 = ListFolderV2DTO(
                path=path, equipment_no=equipment_no or "WEB", recursive=recursive
            )
            return await self._client.post_json(
                "/api/file/2/files/list_folder",
                ListFolderLocalVO,
                json=dto_v2.to_dict(),
            )
        if folder_id is not None:
            # List folder contents using v3/device API
            dto_v3 = ListFolderLocalDTO(
                id=folder_id,
                equipment_no=equipment_no or "WEB",
                recursive=recursive,
            )
            return await self._client.post_json(
                "/api/file/3/files/list_folder_v3",
                ListFolderLocalVO,
                json=dto_v3.to_dict(),
            )
        raise ValueError("path or folder_id must be specified")

    async def delete(self, id: int, equipment_no: str) -> DeleteFolderLocalVO:
        """Delete a folder or file (V3)."""
        dto = DeleteFolderLocalDTO(id=id, equipment_no=equipment_no)
        return await self._client.post_json(
            "/api/file/3/files/delete_folder_v3",
            DeleteFolderLocalVO,
            json=dto.to_dict(),
        )

    async def delete_by_path(
        self, path: str, equipment_no: str | None = None
    ) -> DeleteFolderLocalVO:
        """Delete a folder or file by path (V3)."""
        if equipment_no is None:
            equipment_no = "WEB"
        info = await self.query_by_path(path, equipment_no)
        if not info.entries_vo:
            raise FileNotFoundError(f"File or folder not found: {path}")
        return await self.delete(int(info.entries_vo.id), equipment_no)

    async def move(
        self, id: int, to_path: str, equipment_no: str, autorename: bool = False
    ) -> FileMoveLocalVO:
        """Move a folder or file (V3)."""
        dto = FileMoveLocalDTO(
            id=id, to_path=to_path, equipment_no=equipment_no, autorename=autorename
        )
        return await self._client.post_json(
            "/api/file/3/files/move_v3", FileMoveLocalVO, json=dto.to_dict()
        )

    async def copy(
        self, id: int, to_path: str, equipment_no: str, autorename: bool = False
    ) -> FileCopyLocalVO:
        """Copy a folder or file (V3)."""
        dto = FileCopyLocalDTO(
            id=id, to_path=to_path, equipment_no=equipment_no, autorename=autorename
        )
        return await self._client.post_json(
            "/api/file/3/files/copy_v3", FileCopyLocalVO, json=dto.to_dict()
        )

    async def upload_content(
        self,
        path: str,
        content: bytes,
        equipment_no: str | None = None,
        chunk_size: int = 5 * 1024 * 1024,
    ) -> FileUploadFinishLocalVO:
        """Create a file (convenience method wrapping upload flow).

        Args:
            path: Full cloud path (e.g. /Folder/file.txt)
            content: File content (string or bytes)
            equipment_no: Equipment number
            chunk_size: Upload chunk size/part size

        Returns:
            FileUploadFinishLocalVO containing file upload finish response
        """
        if equipment_no is None:
            equipment_no = "WEB"
        filename = Path(path).name
        size = len(content)

        # First upload the upload url
        _LOGGER.debug("Initiating upload for file %s", path)
        apply = await self.upload_apply(filename, path, size, equipment_no)

        md5 = hashlib.md5(content).hexdigest()

        await self._client._upload_to_oss(
            content,
            filename,
            apply.full_upload_url,
            apply.part_upload_url,
            chunk_size,
        )

        _LOGGER.debug("Finishing upload for file %s", path)

        parent = str(Path(path).parent)
        if parent == ".":
            parent = ""
        parent_path_str = parent.strip("/")

        return await self.upload_finish(
            file_name=filename,
            path=parent_path_str,
            content_hash=md5,
            equipment_no=equipment_no,
            inner_name=apply.inner_name,
        )

    async def upload_apply(
        self, file_name: str, path: str, size: int, equipment_no: str
    ) -> FileUploadApplyLocalVO:
        """Apply for file upload."""
        dto = FileUploadApplyLocalDTO(
            file_name=file_name, path=path, size=str(size), equipment_no=equipment_no
        )
        return await self._client.post_json(
            "/api/file/3/files/upload/apply", FileUploadApplyLocalVO, json=dto.to_dict()
        )

    async def upload_finish(
        self,
        file_name: str,
        path: str,
        content_hash: str,
        equipment_no: str,
        inner_name: str | None = None,
    ) -> FileUploadFinishLocalVO:
        """Finish file upload."""
        dto = FileUploadFinishLocalDTO(
            file_name=file_name,
            path=path,
            content_hash=content_hash,
            equipment_no=equipment_no,
            inner_name=inner_name,
        )
        return await self._client.post_json(
            "/api/file/2/files/upload/finish",
            FileUploadFinishLocalVO,
            json=dto.to_dict(),
        )

    async def download_content(
        self,
        path: str | None = None,
        file_id: int | None = None,
        equipment_no: str = "",
        offset: int = 0,
        length: int = -1,
    ) -> bytes:
        """Download file content, optionally with range.

        Args:
           path: File path (e.g. /Folder/file.pdf) (optional if file_id provided)
           file_id: File ID (optional if path provided)
           equipment_no: Equipment number
           offset: Start byte offset
           length: Number of bytes to read (-1 for until end)

        Returns:
            File content bytes
        """
        if equipment_no == "":
            equipment_no = "WEB"

        if file_id is None:
            if path is None:
                raise ValueError("Either path or file_id must be provided")
            # Resolve path to ID
            info = await self.query_by_path(path, equipment_no)
            if not info.entries_vo:
                raise FileNotFoundError(f"File not found: {path}")
            # The API returns id as str, we need int for download_v3
            file_id = int(info.entries_vo.id)

        download_info = await self.download_v3(file_id, equipment_no)
        url = download_info.url

        headers = {}
        if offset > 0 or length != -1:
            end = ""
            if length != -1:
                end = str(offset + length - 1)
            headers["Range"] = f"bytes={offset}-{end}"

        return await self._client.get_content(url, headers=headers)

    async def download_v3(self, file_id: int, equipment_no: str) -> FileDownloadLocalVO:
        """Get download URL (V3)."""
        dto = FileDownloadLocalDTO(id=file_id, equipment_no=equipment_no)
        return await self._client.post_json(
            "/api/file/3/files/download_v3", FileDownloadLocalVO, json=dto.to_dict()
        )

    async def get_capacity(self, equipment_no: str = "") -> CapacityLocalVO:
        """Get storage capacity (Device)."""
        dto = CapacityLocalDTO(equipment_no=equipment_no)
        return await self._client.post_json(
            "/api/file/2/users/get_space_usage", CapacityLocalVO, json=dto.to_dict()
        )

    async def query_by_path(
        self, path: str, equipment_no: str
    ) -> FileQueryByPathLocalVO:
        """Query file info by path (V3)."""
        dto = FileQueryByPathLocalDTO(path=path, equipment_no=equipment_no)
        return await self._client.post_json(
            "/api/file/3/files/query/by/path_v3",
            FileQueryByPathLocalVO,
            json=dto.to_dict(),
        )

    async def query_by_id(self, file_id: int, equipment_no: str) -> FileQueryLocalVO:
        """Query file info by ID (V3)."""
        dto = FileQueryLocalDTO(id=str(file_id), equipment_no=equipment_no)
        return await self._client.post_json(
            "/api/file/3/files/query_v3", FileQueryLocalVO, json=dto.to_dict()
        )

    async def sync_start(self, equipment_no: str) -> SynchronousStartLocalVO:
        """Start sync session."""
        dto = SynchronousStartLocalDTO(equipment_no=equipment_no)
        return await self._client.post_json(
            "/api/file/2/files/synchronous/start",
            SynchronousStartLocalVO,
            json=dto.to_dict(),
        )

    async def sync_end(self, equipment_no: str) -> SynchronousEndLocalVO:
        """End sync session."""
        dto = SynchronousEndLocalDTO(equipment_no=equipment_no)
        return await self._client.post_json(
            "/api/file/2/files/synchronous/end",
            SynchronousEndLocalVO,
            json=dto.to_dict(),
        )

    async def note_to_png(self, file_id: int) -> PngVO:
        """Convert a note to PNG (Device API)."""
        dto = PngDTO(id=file_id)
        return await self._client.post_json(
            "/api/file/note/to/png", PngVO, json=dto.to_dict()
        )

    async def note_to_pdf(
        self, file_id: int, page_no_list: list[int] | None = None
    ) -> PdfVO:
        """Convert a note to PDF (Device API)."""
        dto = PdfDTO(id=file_id, page_no_list=page_no_list or [])
        return await self._client.post_json(
            "/api/file/note/to/pdf", PdfVO, json=dto.to_dict()
        )

    async def get_note_png_pages(self, file_id: int) -> list[bytes]:
        """Convenience method to get PNG content for all pages of a note."""
        conversion = await self.note_to_png(file_id)
        pages = []
        for page_vo in conversion.png_page_vo_list:
            content = await self._client.get_content(page_vo.url)
            pages.append(content)
        return pages

    async def get_note_pdf(
        self, file_id: int, page_no_list: list[int] | None = None
    ) -> bytes:
        """Convenience method to get PDF content for a note."""
        conversion = await self.note_to_pdf(file_id, page_no_list)
        if not conversion.url:
            raise ValueError("Conversion failed: no URL returned")
        return await self._client.get_content(conversion.url)
