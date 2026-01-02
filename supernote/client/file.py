from typing import Any

from supernote.models.base import BaseResponse
from supernote.models.file import (
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
    FileLabelSearchDTO,
    FileLabelSearchVO,
    FileMoveLocalDTO,
    FileMoveLocalVO,
    FileQueryByPathLocalDTO,
    FileQueryByPathLocalVO,
    FileQueryLocalDTO,
    FileQueryLocalVO,
    FileUploadApplyLocalDTO,
    FileUploadApplyLocalVO,
    FileUploadFinishLocalDTO,
    FileUploadFinishLocalVO,
    ListFolderLocalDTO,
    ListFolderLocalVO,
    ListFolderV2DTO,
    RecycleFileDTO,
    RecycleFileListDTO,
    RecycleFileListVO,
    SynchronousEndLocalDTO,
    SynchronousEndLocalVO,
    SynchronousStartLocalDTO,
    SynchronousStartLocalVO,
)

from . import Client


class FileClient:
    """Client for File APIs (Device/Sync) using standard DTOs."""

    def __init__(self, client: Client) -> None:
        """Initialize the FileClient."""
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

    async def delete_folder(
        self, folder_id: int, equipment_no: str
    ) -> DeleteFolderLocalVO:
        """Delete a folder or file (V3)."""
        dto = DeleteFolderLocalDTO(id=folder_id, equipment_no=equipment_no)
        return await self._client.post_json(
            "/api/file/3/files/delete_folder_v3",
            DeleteFolderLocalVO,
            json=dto.to_dict(),
        )

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
    ) -> FileUploadFinishLocalVO:
        """Finish file upload."""
        dto = FileUploadFinishLocalDTO(
            file_name=file_name,
            path=path,
            content_hash=content_hash,
            equipment_no=equipment_no,
        )
        return await self._client.post_json(
            "/api/file/2/files/upload/finish",
            FileUploadFinishLocalVO,
            json=dto.to_dict(),
        )

    async def download_v3(self, file_id: int, equipment_no: str) -> FileDownloadLocalVO:
        """Get download URL (V3)."""
        dto = FileDownloadLocalDTO(id=file_id, equipment_no=equipment_no)
        return await self._client.post_json(
            "/api/file/3/files/download_v3", FileDownloadLocalVO, json=dto.to_dict()
        )

    async def get_capacity(self, equipment_no: str = "") -> CapacityLocalVO:
        """Get storage capacity."""
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

    async def recycle_list(
        self, page_no: int = 1, page_size: int = 50
    ) -> RecycleFileListVO:
        """List recycle bin."""
        dto = RecycleFileListDTO(page_no=page_no, page_size=page_size)
        return await self._client.post_json(
            "/api/file/recycle/list/query", RecycleFileListVO, json=dto.to_dict()
        )

    async def recycle_delete(self, id_list: list[int]) -> None:
        """Delete from recycle bin."""
        dto = RecycleFileDTO(id_list=id_list)
        await self._client.post_json(
            "/api/file/recycle/delete", BaseResponse, json=dto.to_dict()
        )

    async def recycle_revert(self, id_list: list[int]) -> None:
        """Revert from recycle bin."""
        dto = RecycleFileDTO(id_list=id_list)
        await self._client.post_json(
            "/api/file/recycle/revert", BaseResponse, json=dto.to_dict()
        )

    async def recycle_clear(self) -> None:
        """Clear recycle bin."""
        await self._client.post_json("/api/file/recycle/clear", BaseResponse, json={})

    async def search(
        self, keyword: str, equipment_no: str | None = None
    ) -> FileLabelSearchVO:
        """Search files by keyword."""
        dto = FileLabelSearchDTO(keyword=keyword, equipment_no=equipment_no)
        return await self._client.post_json(
            "/api/file/label/list/search", FileLabelSearchVO, json=dto.to_dict()
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

    async def upload_data(
        self, filename: str, data: Any, params: dict | None = None
    ) -> None:
        """Upload file data (Device/V3)."""
        # Pass empty dict to headers to avoid default application/json Content-Type
        # The client will still add Auth and XSRF headers
        await self._client.request(
            "post",
            f"/api/file/upload/data/{filename}",
            data=data,
            params=params,
            headers={},
        )
