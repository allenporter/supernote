"""File related API data models mirroring OpenAPI Spec."""

from enum import Enum
from dataclasses import dataclass, field
from typing import List

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseResponse, BaseEnum


class FileSortOrder(str, BaseEnum):
    """Sort order for file listing."""
    FILENAME = "filename"
    TIME = "time"
    SIZE = "size"


class FileSortSequence(str, BaseEnum):
    """Sort sequence for file listing."""
    ASC = "asc"
    DESC = "desc"


@dataclass
class FileListQueryDTO(DataClassJSONMixin):
    """Request model for querying a list of files in a directory (ID-based)."""
    directory_id: int = field(metadata=field_options(alias="directoryId"))
    order: FileSortOrder = FileSortOrder.TIME
    sequence: FileSortSequence = FileSortSequence.DESC
    page_no: int = field(metadata=field_options(alias="pageNo"), default=1)
    page_size: int = field(metadata=field_options(alias="pageSize"), default=20)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UserFileVO(DataClassJSONMixin):
    """Object representing a file or folder in the Cloud API."""
    id: str
    directory_id: str = field(metadata=field_options(alias="directoryId"))
    file_name: str = field(metadata=field_options(alias="fileName"))
    size: int
    md5: str
    is_folder: str = field(metadata=field_options(alias="isFolder"))  # "Y", "N"
    create_time: str = field(metadata=field_options(alias="createTime"))  # ISO 8601
    update_time: str = field(metadata=field_options(alias="updateTime"))  # ISO 8601

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileListQueryVO(BaseResponse):
    """Response model containing a paginated list of files."""
    total: int = 0
    pages: int = 0
    page_num: int = field(metadata=field_options(alias="pageNum"), default=0)
    page_size: int = field(metadata=field_options(alias="pageSize"), default=20)
    user_file_vo_list: List[UserFileVO] = field(
        metadata=field_options(alias="userFileVOList"), default_factory=list
    )


@dataclass
class FolderListQueryDTO(DataClassJSONMixin):
    """Request model for listing details of specific folders by ID."""
    directory_id: int = field(metadata=field_options(alias="directoryId"))
    id_list: List[int] = field(metadata=field_options(alias="idList"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FolderVO(DataClassJSONMixin):
    """Object representing a folder."""
    id: str
    directory_id: str = field(metadata=field_options(alias="directoryId"))
    file_name: str = field(metadata=field_options(alias="fileName"))
    empty: str = "N"  # Y/N

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FolderListQueryVO(BaseResponse):
    """Response model containing a list of folders."""
    folder_vo_list: List[FolderVO] = field(
        metadata=field_options(alias="folderVOList"), default_factory=list
    )


@dataclass
class AllocationVO(DataClassJSONMixin):
    """Object representing storage allocation stats."""
    tag: str = "personal"
    allocated: int = 0  # int64

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class CapacityVO(BaseResponse):
    """Response model for cloud storage capacity query."""
    used_capacity: int = field(metadata=field_options(alias="usedCapacity"), default=0)
    total_capacity: int = field(metadata=field_options(alias="totalCapacity"), default=0)


@dataclass
class CapacityLocalVO(BaseResponse):
    """Response model for device storage capacity query (replaces legacy)."""
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    used: int = 0
    allocation_vo: AllocationVO | None = field(
        metadata=field_options(alias="allocationVO"), default=None
    )


@dataclass
class CapacityLocalDTO(DataClassJSONMixin):
    """Request model for device storage capacity query."""
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileDeleteDTO(DataClassJSONMixin):
    """Request model for deleting files."""
    id_list: List[int] = field(metadata=field_options(alias="idList"))
    directory_id: int = field(metadata=field_options(alias="directoryId"))
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FolderAddDTO(DataClassJSONMixin):
    """Request model for creating a new folder."""
    file_name: str = field(metadata=field_options(alias="fileName"))
    directory_id: int = field(metadata=field_options(alias="directoryId"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileMoveAndCopyDTO(DataClassJSONMixin):
    """Request model for moving or copying files."""
    id_list: List[int] = field(metadata=field_options(alias="idList"))
    directory_id: int = field(metadata=field_options(alias="directoryId"))
    go_directory_id: int = field(metadata=field_options(alias="goDirectoryId"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileReNameDTO(DataClassJSONMixin):
    """Request model for renaming a file."""
    id: int
    new_name: str = field(metadata=field_options(alias="newName"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileListSearchDTO(DataClassJSONMixin):
    """Request model for searching files."""
    file_name: str = field(metadata=field_options(alias="fileName"))
    order: FileSortOrder = FileSortOrder.TIME
    sequence: FileSortSequence = FileSortSequence.DESC
    page_no: int = field(metadata=field_options(alias="pageNo"), default=1)
    page_size: int = field(metadata=field_options(alias="pageSize"), default=20)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UserFileSearchVO(DataClassJSONMixin):
    """Object representing a file in search results."""
    id: str
    directory_id: str = field(metadata=field_options(alias="directoryId"))
    file_name: str = field(metadata=field_options(alias="fileName"))
    directory_name: str = field(metadata=field_options(alias="directoryName"), default="")
    size: int = 0
    md5: str = ""
    is_folder: str = field(metadata=field_options(alias="isFolder"), default="N")
    update_time: str = field(metadata=field_options(alias="updateTime"), default="")

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileListSearchVO(BaseResponse):
    """Response model containing search results."""
    total: int = 0
    user_file_search_vo_list: List[UserFileSearchVO] = field(
        metadata=field_options(alias="userFileSearchVOList"), default_factory=list
    )


@dataclass
class RecycleFileListDTO(DataClassJSONMixin):
    """Request model for listing files in the recycle bin."""
    order: FileSortOrder = FileSortOrder.TIME
    sequence: FileSortSequence = FileSortSequence.DESC
    page_no: int = field(metadata=field_options(alias="pageNo"), default=1)
    page_size: int = field(metadata=field_options(alias="pageSize"), default=20)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class RecycleFileVO(DataClassJSONMixin):
    """Object representing a file in the recycle bin."""
    file_id: str = field(metadata=field_options(alias="fileId"))
    is_folder: str = field(metadata=field_options(alias="isFolder"))
    file_name: str = field(metadata=field_options(alias="fileName"))
    update_time: str = field(metadata=field_options(alias="updateTime"))  # ISO 8601
    size: int = 0

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class RecycleFileListVO(BaseResponse):
    """Response model containing recycle bin items."""
    total: int = 0
    recycle_file_vo_list: List[RecycleFileVO] = field(
        metadata=field_options(alias="recycleFileVOList"), default_factory=list
    )


@dataclass
class RecycleFileDTO(DataClassJSONMixin):
    """Request model for operating on recycled files."""
    id_list: List[int] = field(metadata=field_options(alias="idList"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileDownloadDTO(DataClassJSONMixin):
    """Request model for getting a file download URL."""
    id: int
    type: str = "0"  # "0": Download, "1": Share

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileDownloadUrlVO(BaseResponse):
    """Response model containing a download URL."""
    url: str = ""
    md5: str = ""


@dataclass
class FilePathQueryDTO(DataClassJSONMixin):
    """Request model for querying file path info."""
    id: int

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FilePathQueryVO(BaseResponse):
    """Response model containing file path info."""
    path: str = ""
    id_path: str = field(metadata=field_options(alias="idPath"), default="")


@dataclass
class FileUploadApplyDTO(DataClassJSONMixin):
    """Request model for initiating a file upload (Cloud)."""
    directory_id: int = field(metadata=field_options(alias="directoryId"))
    size: int
    file_name: str = field(metadata=field_options(alias="fileName"))
    md5: str

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileUploadApplyLocalVO(BaseResponse):
    """Response model containing upload credentials/URLs."""
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    bucket_name: str | None = field(
        metadata=field_options(alias="bucketName"), default=None
    )
    inner_name: str | None = field(
        metadata=field_options(alias="innerName"), default=None
    )
    x_amz_date: str | None = field(
        metadata=field_options(alias="xAmzDate"), default=None
    )
    authorization: str | None = None
    full_upload_url: str | None = field(
        metadata=field_options(alias="fullUploadUrl"), default=None
    )
    part_upload_url: str | None = field(
        metadata=field_options(alias="partUploadUrl"), default=None
    )


@dataclass
class FileUploadFinishDTO(DataClassJSONMixin):
    """Request model for completing a file upload (Cloud)."""
    directory_id: int = field(metadata=field_options(alias="directoryId"))
    file_size: int = field(metadata=field_options(alias="fileSize"))
    file_name: str = field(metadata=field_options(alias="fileName"))
    md5: str
    inner_name: str = field(metadata=field_options(alias="innerName"))
    type: str = "2"  # "1": App, "2": Cloud

    class Config(BaseConfig):
        serialize_by_alias = True


# --- Device / Legacy Models (Local DTOs) ---


@dataclass
class SynchronousStartLocalDTO(DataClassJSONMixin):
    """Request model for starting device synchronization."""
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SynchronousStartLocalVO(BaseResponse):
    """Response model for sync start acknowledgement."""
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    syn_type: bool = field(metadata=field_options(alias="synType"), default=True)


@dataclass
class SynchronousEndLocalDTO(DataClassJSONMixin):
    """Request model for ending device synchronization."""
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    flag: str | None = None  # "true" / "false"

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SynchronousEndLocalVO(BaseResponse):
    """Response model for sync end acknowledgement."""
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )


@dataclass
class CreateFolderLocalDTO(DataClassJSONMixin):
    """Request model for creating a folder (Device/Path-based)."""
    path: str
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    autorename: bool = False

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class MetadataVO(DataClassJSONMixin):
    """Object representing basic file metadata."""
    name: str
    tag: str = ""
    id: str = ""
    path_display: str = field(metadata=field_options(alias="path_display"), default="")

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class CreateFolderLocalVO(BaseResponse):
    """Response model for folder creation."""
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    metadata: MetadataVO | None = None


@dataclass
class ListFolderV2DTO(DataClassJSONMixin):
    """Request model for listing folder contents (V2)."""
    path: str
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    recursive: bool = False

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ListFolderLocalDTO(DataClassJSONMixin):
    """Request model for listing folder contents (Device/V3)."""
    id: int  # Device uses ID for listing in v3?
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    recursive: bool = False

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class EntriesVO(DataClassJSONMixin):
    """Object representing a file entry (Device)."""
    id: str
    name: str
    tag: str = ""
    path_display: str = field(metadata=field_options(alias="path_display"), default="")
    content_hash: str | None = field(metadata=field_options(alias="content_hash"), default=None)
    is_downloadable: bool = field(metadata=field_options(alias="is_downloadable"), default=True)
    size: int = 0
    last_update_time: int = field(metadata=field_options(alias="lastUpdateTime"), default=0)
    parent_path: str = field(metadata=field_options(alias="parent_path"), default="")

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ListFolderLocalVO(BaseResponse):
    """Response model containing list of file entries (Device)."""
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    entries: List[EntriesVO] = field(default_factory=list)


@dataclass
class DeleteFolderLocalDTO(DataClassJSONMixin):
    """Request model for deleting a folder (Device)."""
    id: int
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class DeleteFolderLocalVO(BaseResponse):
    """Response model for folder deletion."""
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    metadata: MetadataVO | None = None


@dataclass
class FileUploadApplyLocalDTO(DataClassJSONMixin):
    """Request model for initiating a file upload (Device/Path-based)."""
    path: str
    file_name: str = field(metadata=field_options(alias="fileName"))
    size: str  # Note: Spec says string
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    
    # Not strictly in spec but often needed or legacy
    md5: str | None = field(metadata=field_options(alias="fileMd5"), default=None)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileUploadFinishLocalDTO(DataClassJSONMixin):
    """Request model for completing a file upload (Device/Path-based)."""
    path: str
    file_name: str = field(metadata=field_options(alias="fileName"))
    content_hash: str = field(metadata=field_options(alias="content_hash"))
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    size: str | None = None  # Spec says string
    inner_name: str | None = field(metadata=field_options(alias="innerName"), default=None)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileDownloadLocalDTO(DataClassJSONMixin):
    """Request model for file download (Device)."""
    id: int | str  # Spec says int, usage implies str (path) sometimes? Spec says int64.
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileDownloadLocalVO(BaseResponse):
    """Response model containing file download info (Device)."""
    url: str = ""
    id: str = ""
    name: str = ""
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    path_display: str = field(metadata=field_options(alias="path_display"), default="")
    content_hash: str = field(metadata=field_options(alias="content_hash"), default="")
    is_downloadable: bool = field(metadata=field_options(alias="is_downloadable"), default=True)
    size: int = 0


@dataclass
class FileQueryLocalDTO(DataClassJSONMixin):
    """Request model for querying file info (Device)."""
    id: str
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileQueryLocalVO(BaseResponse):
    """Response model containing file info (Device)."""
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    entries_vo: EntriesVO | None = field(metadata=field_options(alias="entriesVO"), default=None)


@dataclass
class FileQueryByPathLocalDTO(DataClassJSONMixin):
    """Request model for querying file info by path (Device)."""
    path: str
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileQueryByPathLocalVO(BaseResponse):
    """Response model containing file info by path (Device)."""
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    entries_vo: EntriesVO | None = field(metadata=field_options(alias="entriesVO"), default=None)


@dataclass
class FileMoveLocalDTO(DataClassJSONMixin):
    """Request model for moving a file (Device)."""
    id: int
    to_path: str = field(metadata=field_options(alias="to_path"))
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    autorename: bool = False

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileMoveLocalVO(BaseResponse):
    """Response model for file move operation (Device)."""
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    entries_vo: EntriesVO | None = field(metadata=field_options(alias="entriesVO"), default=None)


@dataclass
class FileCopyLocalDTO(DataClassJSONMixin):
    """Request model for copying a file (Device)."""
    id: int
    to_path: str = field(metadata=field_options(alias="to_path"))
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    autorename: bool = False

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileCopyLocalVO(BaseResponse):
    """Response model for file copy operation (Device)."""
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    entries_vo: EntriesVO | None = field(metadata=field_options(alias="entriesVO"), default=None)
