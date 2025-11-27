"""Model classes for the Supernote Cloud API."""

from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.mixins.json import DataClassJSONMixin
from mashumaro.config import BaseConfig


@dataclass
class QueryUserRequest(DataClassJSONMixin):
    """Request to query user."""

    country_code: int = field(metadata=field_options(alias="countryCode"))
    account: str

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class QueryUserResponse(DataClassJSONMixin):
    """Response from query user call."""

    success: bool = True
    error_code: str = field(metadata=field_options(alias="errorCode"), default="")
    error_msg: str = field(metadata=field_options(alias="errorMsg"), default="")
    user_id: str = field(metadata=field_options(alias="userId"))
    user_name: str = field(metadata=field_options(alias="userName"))
    country_code: str = field(metadata=field_options(alias="countryCode"))
    birthday: str = field(metadata=field_options(alias="birthday"))
    telephone: str = field(metadata=field_options(alias="telephone"), default="")
    sex: str = ""
    file_server: str = field(metadata=field_options(alias="fileServer"), default="")


@dataclass
class TokenRequest(DataClassJSONMixin):
    """Request to token endpoint."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class TokenResponse(DataClassJSONMixin):
    """Response from token endpoint."""


@dataclass
class UserRandomCodeRequest(DataClassJSONMixin):
    """Request to get a random code."""

    country_code: int = field(metadata=field_options(alias="countryCode"))
    account: str

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UserRandomCodeResponse(DataClassJSONMixin):
    """Response from login."""

    random_code: str = field(metadata=field_options(alias="randomCode"))
    timestamp: str


@dataclass
class UserLoginRequest(DataClassJSONMixin):
    """Request to login."""

    country_code: int = field(metadata=field_options(alias="countryCode"))
    account: str
    password: str
    browser: str
    equipment: int
    login_method: int = field(metadata=field_options(alias="loginMethod"))
    timestamp: str
    language: str

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class UserLoginResponse(DataClassJSONMixin):
    """Response from access token call."""

    success: bool
    error_code: str = field(metadata=field_options(alias="errorCode"), default="")
    error_msg: str = field(metadata=field_options(alias="errorMsg"), default="")
    token: str


@dataclass(kw_only=True)
class File(DataClassJSONMixin):
    """Representation of a file."""

    id: int
    directory_id: int = field(metadata=field_options(alias="directoryId"))
    file_name: str = field(metadata=field_options(alias="fileName"))
    size: int = 0
    md5: str = ""
    is_folder: str = field(metadata=field_options(alias="isFolder"))  # "Y" or "N"
    create_time: int = field(metadata=field_options(alias="createTime"))
    update_time: int = field(metadata=field_options(alias="updateTime"))


@dataclass
class FileListRequest(DataClassJSONMixin):
    """Request for file list."""

    directory_id: int = field(metadata=field_options(alias="directoryId"))
    page_no: int = field(metadata=field_options(alias="pageNo"))
    page_size: int = field(metadata=field_options(alias="pageSize"), default=20)
    order: str = "time"
    sequence: str = "desc"

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class FileListResponse(DataClassJSONMixin):
    """Response from file list call."""

    success: bool
    error_code: str = field(metadata=field_options(alias="errorCode"), default="")
    error_msg: str = field(metadata=field_options(alias="errorMsg"), default="")
    total: int
    size: int
    pages: int
    file_list: list[File] = field(metadata=field_options(alias="userFileVOList"))


@dataclass
class GetFileDownloadUrlRequest(DataClassJSONMixin):
    """Request for file download."""

    file_id: int = field(metadata=field_options(alias="id"))
    file_type: int = field(metadata=field_options(alias="type"), default=0)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class GetFileDownloadUrlResponse(DataClassJSONMixin):
    """Response from file download call."""

    success: bool
    error_code: str = field(metadata=field_options(alias="errorCode"), default="")
    error_msg: str = field(metadata=field_options(alias="errorMsg"), default="")
    url: str
