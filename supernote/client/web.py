import hashlib

from supernote.models.base import BaseResponse
from supernote.models.file import (
    CapacityVO,
    FileDeleteDTO,
    FileLabelSearchDTO,
    FileLabelSearchVO,
    FileListQueryDTO,
    FileListQueryVO,
    FileSortOrder,
    FileSortSequence,
    FileUploadApplyDTO,
    FileUploadApplyLocalVO,
    FileUploadFinishDTO,
    FolderAddDTO,
    FolderVO,
    RecycleFileDTO,
    RecycleFileListDTO,
    RecycleFileListVO,
    UploadType,
)

from . import Client

DEFAULT_PAGE_SIZE = 50


class WebClient:
    """Client for Web APIs."""

    def __init__(self, client: Client) -> None:
        """Initialize the WebClient."""
        self._client = client

    async def list_query(
        self,
        directory_id: int,
        order: FileSortOrder = FileSortOrder.FILENAME,
        sequence: FileSortSequence = FileSortSequence.DESC,
        page_no: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> FileListQueryVO:
        """Query file list (Web API)."""
        dto = FileListQueryDTO(
            directory_id=directory_id,
            order=order,
            sequence=sequence,
            page_no=page_no,
            page_size=page_size,
        )
        return await self._client.post_json(
            "/api/file/list/query", FileListQueryVO, json=dto.to_dict()
        )

    async def get_capacity_web(self) -> CapacityVO:
        """Get storage capacity (Web)."""
        return await self._client.post_json(
            "/api/file/capacity/query", CapacityVO, json={}
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

    async def create_folder(self, parent_id: int, name: str) -> FolderVO:
        """Create a new folder (Web API)."""
        dto = FolderAddDTO(directory_id=parent_id, file_name=name)
        return await self._client.post_json(
            "/api/file/folder/add", FolderVO, json=dto.to_dict()
        )

    async def file_delete(
        self,
        id_list: list[int],
        parent_id: int = 0,
        equipment_no: str | None = None,
    ) -> None:
        """Delete files/folders (Web API)."""
        dto = FileDeleteDTO(
            id_list=id_list, directory_id=parent_id, equipment_no=equipment_no
        )
        await self._client.post_json(
            "/api/file/delete", BaseResponse, json=dto.to_dict()
        )

    async def upload_file(self, parent_id: int, name: str, content: bytes) -> None:
        """Upload a file (Web API)."""
        md5 = hashlib.md5(content).hexdigest()
        size = len(content)

        # Apply to get an upload endpoint
        dto = FileUploadApplyDTO(
            directory_id=parent_id,
            file_name=name,
            size=size,
            md5=md5,
        )
        apply_vo = await self._client.post_json(
            "/api/file/upload/apply", FileUploadApplyLocalVO, json=dto.to_dict()
        )

        # Upload to OSS (using signed URL)
        await self._client._upload_to_oss(
            content,
            apply_vo.inner_name or "",
            apply_vo.full_upload_url,
            apply_vo.part_upload_url,
        )

        # Finish upload
        finish_dto = FileUploadFinishDTO(
            directory_id=parent_id,
            file_size=size,
            file_name=name,
            md5=md5,
            inner_name=apply_vo.inner_name or "",
            type=UploadType.CLOUD,
        )
        await self._client.post_json(
            "/api/file/upload/finish", BaseResponse, json=finish_dto.to_dict()
        )
