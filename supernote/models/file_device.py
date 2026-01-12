from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseResponse
from .file_common import EntriesVO


@dataclass
class AllocationVO(DataClassJSONMixin):
    """Object representing storage allocation stats."""

    tag: str = "personal"
    allocated: int = 0  # int64

    class Config(BaseConfig):
        serialize_by_alias = True


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
class ListFolderLocalVO(BaseResponse):
    """Response model containing list of file entries (Device).

    This is used by the following POST endpoint:
        /api/file/2/files/list_folder
        /api/file/3/files/list_folder_v3
    """

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    entries: list[EntriesVO] = field(default_factory=list)


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
    """Obfuscated storage filename: {UUID}-{tail}.{ext} where tail is derived from the the client equipmentNo"""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileUploadFinishLocalVO(BaseResponse):
    """Response model for completing a file upload (Device/Path-based).

    This is used by the following POST endpoint:
        /api/file/2/files/upload/finish
    """

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    path_display: str | None = field(
        metadata=field_options(alias="path_display"), default=None
    )
    id: str | None = None
    size: int = 0
    name: str | None = None
    content_hash: str | None = field(
        metadata=field_options(alias="content_hash"), default=None
    )


@dataclass
class FileDownloadLocalDTO(DataClassJSONMixin):
    """Request model for file download (Device).

    This is used by the following POST endpoint:
        /api/file/3/files/download_v3
    """

    id: int
    """File id number from the devices api."""

    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    """Equipment number."""

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


@dataclass
class TerminalFileUploadApplyDTO(DataClassJSONMixin):
    """Request model for initiating a terminal file upload.

    Used by:
        /api/file/terminal/upload/apply (POST)
    """

    file_size: str = field(metadata=field_options(alias="fileSize"))
    file_name: str = field(metadata=field_options(alias="fileName"))
    md5: str
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    file_path: str | None = field(
        metadata=field_options(alias="filePath"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class TerminalFileUploadFinishDTO(DataClassJSONMixin):
    """Request model for completing a terminal file upload.

    Used by:
        /api/file/terminal/upload/apply
    """

    file_size: str = field(metadata=field_options(alias="fileSize"))
    file_name: str = field(metadata=field_options(alias="fileName"))
    md5: str
    inner_name: str = field(metadata=field_options(alias="innerName"))
    """Obfuscated storage filename: {UUID}-{tail}.{ext} where tail is derived from the the client equipmentNo"""
    modify_time: str = field(metadata=field_options(alias="modifyTime"))
    upload_time: str = field(metadata=field_options(alias="uploadTime"))

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    file_path: str | None = field(
        metadata=field_options(alias="filePath"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class PdfDTO(DataClassJSONMixin):
    """Request model for converting a note to PDF.

    This is used by the following POST endpoint:
        /api/file/note/to/pdf
    """

    id: int
    page_no_list: list[int] = field(
        metadata=field_options(alias="pageNoList"), default_factory=list
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class PdfVO(BaseResponse):
    """Response model for PDF conversion.

    This is used by the following POST endpoint:
        /api/file/note/to/pdf
    """

    url: str | None = None


@dataclass
class PngDTO(DataClassJSONMixin):
    """Request model for converting a note to PNG.

    This is used by the following POST endpoint:
        /api/file/note/to/png
    """

    id: int

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class PngPageVO(DataClassJSONMixin):
    """Object representing a single converted PNG page."""

    page_no: int = field(metadata=field_options(alias="pageNo"))
    url: str

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class PngVO(BaseResponse):
    """Response model for PNG conversion.

    This is used by the following POST endpoint:
        /api/file/note/to/png
    """

    png_page_vo_list: list[PngPageVO] = field(
        metadata=field_options(alias="pngPageVOList"), default_factory=list
    )
