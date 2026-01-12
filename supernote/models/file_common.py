from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseEnum, BaseResponse


class FileSortOrder(str, BaseEnum):
    """Sort order for file listing."""

    FILENAME = "filename"
    TIME = "time"
    SIZE = "size"


class FileSortSequence(str, BaseEnum):
    """Sort sequence for file listing."""

    ASC = "asc"
    DESC = "desc"


class DownloadType(str, BaseEnum):
    """Download type."""

    DOWNLOAD = "0"
    SHARE = "1"


class UploadType(str, BaseEnum):
    """Upload type."""

    APP = "1"
    CLOUD = "2"


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
    """In private clouds, typically 'supernote'."""

    inner_name: str | None = field(
        metadata=field_options(alias="innerName"), default=None
    )
    """Obfuscated storage key. Formula: {UUID}-{tail}.{ext} where tail is SN last 3 digits."""

    x_amz_date: str | None = field(
        metadata=field_options(alias="xAmzDate"), default=None
    )
    authorization: str | None = None
    """The signature for the upload request which should be passed in the x-access-token header."""
    full_upload_url: str | None = field(
        metadata=field_options(alias="fullUploadUrl"), default=None
    )
    part_upload_url: str | None = field(
        metadata=field_options(alias="partUploadUrl"), default=None
    )
