from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseResponse, BooleanEnum
from .file_common import (
    DownloadType,
    EntriesVO,
    FileSortOrder,
    FileSortSequence,
    UploadType,
)


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
    user_file_vo_list: list[UserFileVO] = field(
        metadata=field_options(alias="userFileVOList"), default_factory=list
    )


@dataclass
class FolderListQueryDTO(DataClassJSONMixin):
    """Request model for listing details of specific folders by ID.

    This is used by the following POST endpoint:
        /api/file/folder/list/query
    """

    directory_id: int = field(metadata=field_options(alias="directoryId"))
    id_list: list[int] = field(metadata=field_options(alias="idList"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FolderVO(BaseResponse):
    """Object representing a folder."""

    id: str = ""
    directory_id: str = field(metadata=field_options(alias="directoryId"), default="")
    file_name: str = field(metadata=field_options(alias="fileName"), default="")
    empty: BooleanEnum = field(
        metadata=field_options(alias="empty"), default=BooleanEnum.NO
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FolderListQueryVO(BaseResponse):
    """Response model containing a list of folders.

    This is used by the following POST endpoint:
        /api/file/folder/list/query
    """

    folder_vo_list: list[FolderVO] = field(
        metadata=field_options(alias="folderVOList"), default_factory=list
    )


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
class FileDeleteDTO(DataClassJSONMixin):
    """Request model for deleting files.

    This is used by the following POST endpoint:
        /api/file/delete
    """

    id_list: list[int] = field(metadata=field_options(alias="idList"))
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
    """The name of the folder."""

    directory_id: int = field(metadata=field_options(alias="directoryId"), default=0)
    """The parent directory ID. If not specified, the root directory is used."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileMoveAndCopyDTO(DataClassJSONMixin):
    """Request model for moving or copying files.

    This is used by the following POST endpoint:
        /api/file/move
        /api/file/copy
    """

    id_list: list[int] = field(metadata=field_options(alias="idList"))
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
    user_file_search_vo_list: list[UserFileSearchVO] = field(
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
    recycle_file_vo_list: list[RecycleFileVO] = field(
        metadata=field_options(alias="recycleFileVOList"), default_factory=list
    )


@dataclass
class RecycleFileDTO(DataClassJSONMixin):
    """Request model for operating on recycled files.

    This is used by the following POST endpoint:
        /api/file/recycle/delete
        /api/file/recycle/revert
    """

    id_list: list[int] = field(metadata=field_options(alias="idList"))

    class Config(BaseConfig):
        serialize_by_alias = True


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

    file_name: str = field(metadata=field_options(alias="fileName"))
    size: int
    md5: str

    directory_id: int = field(metadata=field_options(alias="directoryId"), default=0)
    """Represents the directory ID where the file will be stored."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileUploadFinishDTO(DataClassJSONMixin):
    """Request model for completing a file upload (Cloud).

    This is used by the following POST endpoint:
        /api/file/upload/finish
    """

    file_size: int = field(metadata=field_options(alias="fileSize"))
    file_name: str = field(metadata=field_options(alias="fileName"))
    md5: str
    inner_name: str = field(metadata=field_options(alias="innerName"))
    """Obfuscated storage key. Formula: {UUID}-{tail}.{ext} where tail is SN last 3 digits."""

    directory_id: int = field(metadata=field_options(alias="directoryId"), default=0)
    """Represents the directory ID where the file will be stored or 0 means the root."""

    type: UploadType = UploadType.CLOUD

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FolderFileAddDTO(DataClassJSONMixin):
    """Request model for adding a folder or file.

    Used by:
        /api/file/add/folder/file (POST)
    """

    file_name: str = field(metadata=field_options(alias="fileName"))
    """The name of the file or folder to be added (allows renaming)."""

    file_id: int = field(metadata=field_options(alias="fileId"))
    """The ID of the file or folder to be added."""

    directory_id: int = field(metadata=field_options(alias="directoryId"))
    """Represents the source directory ID where the file or folder currently exists."""

    go_directory_id: int = field(metadata=field_options(alias="goDirectoryId"))
    """Represents the destination directory ID where the file or folder will be moved to."""

    is_folder: str = field(metadata=field_options(alias="isFolder"))
    """Y: Folder, N: File"""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileQueryV2DTO(DataClassJSONMixin):
    """Request model for querying file info V2.

    Used by:
        /api/file/2/files (POST)
    """

    id: str
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class FileQueryV2VO(BaseResponse):
    """Response model for file query V2.

    Used by:
        /api/file/2/files (POST)
    """

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    entries_vo: EntriesVO | None = field(
        metadata=field_options(alias="entriesVO"), default=None
    )


@dataclass
class FileQueryByPathV2DTO(DataClassJSONMixin):
    """Request model for querying file by path V2.

    Used by:
        /api/file/2/files/query_by_path
    """

    file_name: str | None = field(
        metadata=field_options(alias="fileName"), default=None
    )
    path: str | None = None
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class FileQueryByPathV2VO(BaseResponse):
    """Response model for file query by path V2.

    Used by:
        /api/file/2/files/query_by_path
    """

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    entries_vo: EntriesVO | None = field(
        metadata=field_options(alias="entriesVO"), default=None
    )


@dataclass
class PdfDTO(DataClassJSONMixin):
    """Request model to convert note to PDF.

    Used by:
        /api/file/note/to/pdf (POST)
    """

    id: int
    page_no_list: list[int] | None = field(
        metadata=field_options(alias="pageNoList"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class PdfVO(BaseResponse):
    """Response model for PDF conversion.

    Used by:
        /api/file/note/to/pdf (POST)
    """

    url: str | None = None


@dataclass
class PngDTO(DataClassJSONMixin):
    """Request model to convert note to PNG.

    Used by:
        /api/file/note/to/png (POST)
    """

    id: int

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class PngPageVO(DataClassJSONMixin):
    """Object representing a PNG page."""

    page_no: int | None = field(metadata=field_options(alias="pageNo"), default=None)
    url: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class PngVO(BaseResponse):
    """Response model for PNG conversion.

    Used by:
        /api/file/note/to/png (POST)
    """

    png_page_vo_list: list[PngPageVO] | None = field(
        metadata=field_options(alias="pngPageVOList"), default=None
    )


@dataclass
class FileLabelSearchDTO(DataClassJSONMixin):
    """Request model for searching files by label/keyword.

    Used by:
        /api/file/label/list/search (POST)
    """

    keyword: str
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileLabelSearchVO(BaseResponse):
    """Response model for file label search.

    Used by:
        /api/file/label/list/search (POST)
    """

    entries: list[EntriesVO] = field(default_factory=list)
