from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.config import TO_DICT_ADD_OMIT_NONE_FLAG, BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseResponse


@dataclass
class SyncStartResponse(BaseResponse):
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    syn_type: bool = field(metadata=field_options(alias="synType"), default=True)


@dataclass
class SyncStartRequest(DataClassJSONMixin):
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class SyncEndRequest(DataClassJSONMixin):
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    flag: str | None = None  # "true" or "false"

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class ListFolderRequest(DataClassJSONMixin):
    path: str = "/"
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class FileEntryVO(DataClassJSONMixin):
    tag: str  # "folder" or "file"
    id: str
    name: str
    path_display: str = field(metadata=field_options(alias="path_display"))
    parent_path: str = field(metadata=field_options(alias="parent_path"))
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

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class ListFolderResponse(BaseResponse):
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    entries: list[FileEntryVO] = field(default_factory=list)


@dataclass
class AllocationVO(DataClassJSONMixin):
    tag: str = "personal"
    allocated: int = 0

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class CapacityResponse(BaseResponse):
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    used: int = 0
    allocation_vo: AllocationVO | None = field(
        metadata=field_options(alias="allocationVO"), default=None
    )


@dataclass
class FileQueryRequest(DataClassJSONMixin):
    path: str
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class FileQueryByIdRequest(DataClassJSONMixin):
    id: str
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class FileQueryResponse(BaseResponse):
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    entries_vo: FileEntryVO | None = field(
        metadata=field_options(alias="entriesVO"), default=None
    )


@dataclass
class UploadApplyRequest(DataClassJSONMixin):
    file_name: str = field(metadata=field_options(alias="fileName"))
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class UploadApplyResponse(BaseResponse):
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
class UploadFinishRequest(DataClassJSONMixin):
    file_name: str = field(metadata=field_options(alias="fileName"))
    path: str
    content_hash: str = field(metadata=field_options(alias="content_hash"))
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class UploadFinishResponse(BaseResponse):
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
class DownloadApplyRequest(DataClassJSONMixin):
    id: str

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class DownloadApplyResponse(BaseResponse):
    url: str | None = None


@dataclass
class CreateDirectoryRequest(DataClassJSONMixin):
    path: str
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    autorename: bool = False

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class CreateDirectoryResponse(BaseResponse):
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )


@dataclass
class DeleteRequest(DataClassJSONMixin):
    id: int
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class DeleteResponse(BaseResponse):
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )


@dataclass
class FileMoveRequest(DataClassJSONMixin):
    id: int
    to_path: str = field(metadata=field_options(alias="to_path"))
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    autorename: bool = False

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class FileMoveResponse(BaseResponse):
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )


@dataclass
class FileCopyRequest(DataClassJSONMixin):
    id: int
    to_path: str = field(metadata=field_options(alias="to_path"))
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    autorename: bool = False

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class FileCopyResponse(BaseResponse):
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )


@dataclass
class RecycleFileVO(DataClassJSONMixin):
    file_id: str = field(metadata=field_options(alias="fileId"))
    is_folder: str = field(metadata=field_options(alias="isFolder"))
    file_name: str = field(metadata=field_options(alias="fileName"))
    size: int = 0
    update_time: int = field(metadata=field_options(alias="updateTime"), default=0)

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class RecycleFileListRequest(DataClassJSONMixin):
    order: str = "time"  # filename, time, size
    sequence: str = "desc"  # asc or desc
    page_no: int = field(metadata=field_options(alias="pageNo"), default=1)
    page_size: int = field(metadata=field_options(alias="pageSize"), default=20)

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class RecycleFileListResponse(BaseResponse):
    total: int = 0
    recycle_file_vo_list: list[RecycleFileVO] = field(
        metadata=field_options(alias="recycleFileVOList"), default_factory=list
    )


@dataclass
class RecycleFileRequest(DataClassJSONMixin):
    id_list: list[int] = field(metadata=field_options(alias="idList"))

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class FileSearchRequest(DataClassJSONMixin):
    keyword: str
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class FileSearchResponse(BaseResponse):
    entries: list[FileEntryVO] = field(default_factory=list)
