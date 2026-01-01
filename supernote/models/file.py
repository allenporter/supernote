"""File related API data models mirroring OpenAPI Spec."""

from dataclasses import dataclass, field
from typing import List

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseEnum, BaseResponse, BooleanEnum


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
    """Request model for querying a list of files in a directory (ID-based).

    This is used by the following POST endpoint:
        /api/file/list/query
    """

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
    size: int | None = None
    md5: str | None = None
    inner_name: str | None = field(
        metadata=field_options(alias="innerName"), default=None
    )
    """Obfuscated storage key. Formula: {UUID}-{tail}.{ext} where tail is SN last 3 digits."""

    is_folder: BooleanEnum = field(
        metadata=field_options(alias="isFolder"), default=BooleanEnum.NO
    )

    create_time: int | None = field(
        metadata=field_options(alias="createTime"), default=None
    )
    """The creation time of the file in milliseconds since epoch."""

    update_time: int | None = field(
        metadata=field_options(alias="updateTime"), default=None
    )
    """The last update time of the file in milliseconds since epoch."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileListQueryVO(BaseResponse):
    """Response model containing a paginated list of files.

    This is used by the following POST endpoint:
        /api/file/list/query
    """

    total: int = 0
    pages: int = 0
    page_num: int = field(metadata=field_options(alias="pageNum"), default=0)
    page_size: int = field(metadata=field_options(alias="pageSize"), default=20)
    user_file_vo_list: List[UserFileVO] = field(
        metadata=field_options(alias="userFileVOList"), default_factory=list
    )


@dataclass
class FolderListQueryDTO(DataClassJSONMixin):
    """Request model for listing details of specific folders by ID.

    This is used by the following POST endpoint:
        /api/file/folder/list/query
    """

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
    empty: BooleanEnum = field(metadata=field_options(alias="empty"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FolderListQueryVO(BaseResponse):
    """Response model containing a list of folders.

    This is used by the following POST endpoint:
        /api/file/folder/list/query
    """

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
    """Response model for cloud storage capacity query.

    This is used by the following POST endpoint:
        /api/file/capacity/query
    """

    used_capacity: int = field(metadata=field_options(alias="usedCapacity"), default=0)
    total_capacity: int = field(
        metadata=field_options(alias="totalCapacity"), default=0
    )


@dataclass
class CapacityLocalVO(BaseResponse):
    """Response model for device storage capacity query (replaces legacy).

    This is used by the following POST endpoint:
        /api/file/2/users/get_space_usage
    """

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    used: int = 0
    allocation_vo: AllocationVO | None = field(
        metadata=field_options(alias="allocationVO"), default=None
    )


@dataclass
class CapacityLocalDTO(DataClassJSONMixin):
    """Request model for device storage capacity query.

    This is used by the following POST endpoint:
        /api/file/2/users/get_space_usage
    """

    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileDeleteDTO(DataClassJSONMixin):
    """Request model for deleting files.

    This is used by the following POST endpoint:
        /api/file/delete
    """

    id_list: List[int] = field(metadata=field_options(alias="idList"))
    directory_id: int = field(metadata=field_options(alias="directoryId"))
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FolderAddDTO(DataClassJSONMixin):
    """Request model for creating a new folder.

    This is used by the following POST endpoint:
        /api/file/folder/add
    """

    file_name: str = field(metadata=field_options(alias="fileName"))
    directory_id: int = field(metadata=field_options(alias="directoryId"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileMoveAndCopyDTO(DataClassJSONMixin):
    """Request model for moving or copying files.

    This is used by the following POST endpoint:
        /api/file/move
        /api/file/copy
    """

    id_list: List[int] = field(metadata=field_options(alias="idList"))
    directory_id: int = field(metadata=field_options(alias="directoryId"))
    go_directory_id: int = field(metadata=field_options(alias="goDirectoryId"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileReNameDTO(DataClassJSONMixin):
    """Request model for renaming a file.

    This is used by the following POST endpoint:
        /api/file/rename
    """

    id: int
    new_name: str = field(metadata=field_options(alias="newName"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileListSearchDTO(DataClassJSONMixin):
    """Request model for searching files.

    This is used by the following POST endpoint:
        /api/file/list/search
    """

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
    directory_name: str = field(
        metadata=field_options(alias="directoryName"), default=""
    )
    size: int = 0
    md5: str = ""
    is_folder: str = field(metadata=field_options(alias="isFolder"), default="N")
    update_time: str = field(metadata=field_options(alias="updateTime"), default="")

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileListSearchVO(BaseResponse):
    """Response model containing search results.

    This is used by the following POST endpoint:
        /api/file/list/search
    """

    total: int = 0
    user_file_search_vo_list: List[UserFileSearchVO] = field(
        metadata=field_options(alias="userFileSearchVOList"), default_factory=list
    )


@dataclass
class RecycleFileListDTO(DataClassJSONMixin):
    """Request model for listing files in the recycle bin.

    This is used by the following POST endpoint:
        /api/file/recycle/list/query
    """

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
    """Response model containing recycle bin items.

    This is used by the following POST endpoint:
        /api/file/recycle/list/query
    """

    total: int = 0
    recycle_file_vo_list: List[RecycleFileVO] = field(
        metadata=field_options(alias="recycleFileVOList"), default_factory=list
    )


@dataclass
class RecycleFileDTO(DataClassJSONMixin):
    """Request model for operating on recycled files.

    This is used by the following POST endpoint:
        /api/file/recycle/delete
        /api/file/recycle/revert
    """

    id_list: List[int] = field(metadata=field_options(alias="idList"))

    class Config(BaseConfig):
        serialize_by_alias = True


class DownloadType(str, BaseEnum):
    """Download type."""

    DOWNLOAD = "0"
    SHARE = "1"


@dataclass
class FileDownloadDTO(DataClassJSONMixin):
    """Request model for getting a file download URL.

    This is used by the following POST endpoint:
        /api/file/download/url
    """

    id: int
    type: DownloadType = DownloadType.DOWNLOAD

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileDownloadUrlVO(BaseResponse):
    """Response model containing a download URL.

    This is used by the following POST endpoint:
        /api/file/download/url
    """

    url: str = ""
    md5: str = ""


@dataclass
class FilePathQueryDTO(DataClassJSONMixin):
    """Request model for querying file path info.

    This is used by the following POST endpoint:
        /api/file/path/query
    """

    id: int

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FilePathQueryVO(BaseResponse):
    """Response model containing file path info.

    This is used by the following POST endpoint:
        /api/file/path/query
    """

    path: str = ""
    id_path: str = field(metadata=field_options(alias="idPath"), default="")


@dataclass
class FileUploadApplyDTO(DataClassJSONMixin):
    """Request model for initiating a file upload (Cloud).

    This is used by the following POST endpoint:
        /api/file/upload/apply
    """

    directory_id: int = field(metadata=field_options(alias="directoryId"))
    size: int
    file_name: str = field(metadata=field_options(alias="fileName"))
    md5: str

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileUploadApplyLocalVO(BaseResponse):
    """Response model containing upload credentials/URLs.

    This is used by the following POST endpoint:
        /api/file/upload/apply
        /api/file/terminal/upload/apply
    """

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    bucket_name: str | None = field(
        metadata=field_options(alias="bucketName"), default=None
    )
    inner_name: str | None = field(
        metadata=field_options(alias="innerName"), default=None
    )
    """Obfuscated storage key. Formula: {UUID}-{tail}.{ext} where tail is SN last 3 digits."""

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


class UploadType(str, BaseEnum):
    """Upload type."""

    APP = "1"
    CLOUD = "2"


@dataclass
class FileUploadFinishDTO(DataClassJSONMixin):
    """Request model for completing a file upload (Cloud).

    This is used by the following POST endpoint:
        /api/file/upload/finish
    """

    directory_id: int = field(metadata=field_options(alias="directoryId"))
    file_size: int = field(metadata=field_options(alias="fileSize"))
    file_name: str = field(metadata=field_options(alias="fileName"))
    md5: str
    inner_name: str = field(metadata=field_options(alias="innerName"))
    """Obfuscated storage key. Formula: {UUID}-{tail}.{ext} where tail is SN last 3 digits."""

    type: UploadType = UploadType.CLOUD

    class Config(BaseConfig):
        serialize_by_alias = True


# --- Device / Legacy Models (Local DTOs) ---


@dataclass
class SynchronousStartLocalDTO(DataClassJSONMixin):
    """Request model for starting device synchronization.

    This is used by the following POST endpoint:
        /api/file/2/files/synchronous/start
    """

    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SynchronousStartLocalVO(BaseResponse):
    """Response model for sync start acknowledgement.

    This is used by the following POST endpoint:
        /api/file/2/files/synchronous/start
    """

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    syn_type: bool = field(metadata=field_options(alias="synType"), default=True)
    """True: normal sync, false: full re-upload."""


@dataclass
class SynchronousEndLocalDTO(DataClassJSONMixin):
    """Request model for ending device synchronization.

    This is used by the following POST endpoint:
        /api/file/2/files/synchronous/end
    """

    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    flag: str | None = None
    """Synchronization success flag typically a string "true" or "false"."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SynchronousEndLocalVO(BaseResponse):
    """Response model for sync end acknowledgement.

    This is used by the following POST endpoint:
        /api/file/2/files/synchronous/end
    """

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )


@dataclass
class CreateFolderLocalDTO(DataClassJSONMixin):
    """Request model for creating a folder (Device/Path-based).

    This is used by the following POST endpoint:
        /api/file/2/files/create_folder_v2
    """

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
    """Response model for folder creation.

    This is used by the following POST endpoint:
        /api/file/2/files/create_folder_v2
    """

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    metadata: MetadataVO | None = None


@dataclass
class ListFolderV2DTO(DataClassJSONMixin):
    """Request model for listing folder contents (V2).

    This is used by the following POST endpoint:
        /api/file/2/files/list_folder
    """

    path: str
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    recursive: bool = False

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ListFolderLocalDTO(DataClassJSONMixin):
    """Request model for listing folder contents (Device/V3).

    This is used by the following POST endpoint:
        /api/file/3/files/list_folder_v3
    """

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
    content_hash: str | None = field(
        metadata=field_options(alias="content_hash"), default=None
    )
    is_downloadable: bool = field(
        metadata=field_options(alias="is_downloadable"), default=True
    )
    size: int = 0
    last_update_time: int = field(
        metadata=field_options(alias="lastUpdateTime"), default=0
    )
    parent_path: str = field(metadata=field_options(alias="parent_path"), default="")

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ListFolderLocalVO(BaseResponse):
    """Response model containing list of file entries (Device).

    This is used by the following POST endpoint:
        /api/file/2/files/list_folder
        /api/file/3/files/list_folder_v3
    """

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    entries: List[EntriesVO] = field(default_factory=list)


@dataclass
class DeleteFolderLocalDTO(DataClassJSONMixin):
    """Request model for deleting a folder (Device).

    This is used by the following POST endpoint:
        /api/file/3/files/delete_folder_v3
    """

    id: int
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class DeleteFolderLocalVO(BaseResponse):
    """Response model for folder deletion.

    This is used by the following POST endpoint:
        /api/file/3/files/delete_folder_v3
    """

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    metadata: MetadataVO | None = None


@dataclass
class FileUploadApplyLocalDTO(DataClassJSONMixin):
    """Request model for initiating a file upload (Device/Path-based).

    This is used by the following POST endpoint:
        /api/file/3/files/upload/apply
    """

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
    """Request model for completing a file upload (Device/Path-based).

    This is used by the following POST endpoint:
        /api/file/2/files/upload/finish
    """

    path: str
    file_name: str = field(metadata=field_options(alias="fileName"))
    content_hash: str = field(metadata=field_options(alias="content_hash"))
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    size: str | None = None  # Spec says string
    inner_name: str | None = field(
        metadata=field_options(alias="innerName"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileDownloadLocalDTO(DataClassJSONMixin):
    """Request model for file download (Device).

    This is used by the following POST endpoint:
        /api/file/3/files/download_v3
    """

    id: int | str  # Spec says int, usage implies str (path) sometimes? Spec says int64.
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileDownloadLocalVO(BaseResponse):
    """Response model containing file download info (Device).

    This is used by the following POST endpoint:
        /api/file/3/files/download_v3
    """

    url: str = ""
    id: str = ""
    name: str = ""
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    path_display: str = field(metadata=field_options(alias="path_display"), default="")
    content_hash: str = field(metadata=field_options(alias="content_hash"), default="")
    is_downloadable: bool = field(
        metadata=field_options(alias="is_downloadable"), default=True
    )
    size: int = 0


@dataclass
class FileQueryLocalDTO(DataClassJSONMixin):
    """Request model for querying file info (Device).

    This is used by the following POST endpoint:
        /api/file/3/files/query_v3
    """

    id: str
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileQueryLocalVO(BaseResponse):
    """Response model containing file info (Device).

    This is used by the following POST endpoint:
        /api/file/3/files/query_v3
    """

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    entries_vo: EntriesVO | None = field(
        metadata=field_options(alias="entriesVO"), default=None
    )


@dataclass
class FileQueryByPathLocalDTO(DataClassJSONMixin):
    """Request model for querying file info by path (Device).

    This is used by the following POST endpoint:
        /api/file/3/files/query/by/path_v3
    """

    path: str
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileQueryByPathLocalVO(BaseResponse):
    """Response model containing file info by path (Device).

    This is used by the following POST endpoint:
        /api/file/3/files/query/by/path_v3
    """

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    entries_vo: EntriesVO | None = field(
        metadata=field_options(alias="entriesVO"), default=None
    )


@dataclass
class FileMoveLocalDTO(DataClassJSONMixin):
    """Request model for moving a file (Device).

    This is used by the following POST endpoint:
        /api/file/3/files/move_v3
    """

    id: int
    to_path: str = field(metadata=field_options(alias="to_path"))
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    autorename: bool = False

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileMoveLocalVO(BaseResponse):
    """Response model for file move operation (Device).

    This is used by the following POST endpoint:
        /api/file/3/files/move_v3
    """

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    entries_vo: EntriesVO | None = field(
        metadata=field_options(alias="entriesVO"), default=None
    )


@dataclass
class FileCopyLocalDTO(DataClassJSONMixin):
    """Request model for copying a file (Device).

    This is used by the following POST endpoint:
        /api/file/3/files/copy_v3
    """

    id: int
    to_path: str = field(metadata=field_options(alias="to_path"))
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    autorename: bool = False

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileCopyLocalVO(BaseResponse):
    """Response model for file copy operation (Device).

    This is used by the following POST endpoint:
        /api/file/3/files/copy_v3
    """

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    entries_vo: EntriesVO | None = field(
        metadata=field_options(alias="entriesVO"), default=None
    )
