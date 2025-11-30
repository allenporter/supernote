"""Model classes for the Supernote Service API."""

from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

COUNTRY_CODE = 1
BROWSER = "Chrome142"
EQUIPMENT = 1
LANGUAGE = "en"


@dataclass
class BaseResponse(DataClassJSONMixin):
    """Base response class."""

    success: bool = True
    error_code: str = field(metadata=field_options(alias="errorCode"), default="")
    error_msg: str = field(metadata=field_options(alias="errorMsg"), default="")


@dataclass
class QueryUserRequest(DataClassJSONMixin):
    """Request to query user."""

    account: str
    country_code: int = field(
        metadata=field_options(alias="countryCode"), default=COUNTRY_CODE
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class QueryUserResponse(BaseResponse):
    """Response from query user call."""

    user_id: str = field(metadata=field_options(alias="userId"))
    user_name: str = field(metadata=field_options(alias="userName"))
    birthday: str = field(metadata=field_options(alias="birthday"))
    country_code: str = field(
        metadata=field_options(alias="countryCode"), default=str(COUNTRY_CODE)
    )
    telephone: str = field(metadata=field_options(alias="telephone"), default="")
    sex: str = ""
    file_server: str = field(metadata=field_options(alias="fileServer"), default="")


@dataclass
class TokenRequest(DataClassJSONMixin):
    """Request to token endpoint."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class TokenResponse(BaseResponse):
    """Response from token endpoint."""


@dataclass
class UserRandomCodeRequest(DataClassJSONMixin):
    """Request to get a random code."""

    account: str
    country_code: int = field(
        metadata=field_options(alias="countryCode"), default=COUNTRY_CODE
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UserRandomCodeResponse(BaseResponse):
    """Response from login."""

    random_code: str = field(metadata=field_options(alias="randomCode"), default="")
    timestamp: str = ""


@dataclass
class UserLoginRequest(DataClassJSONMixin):
    """Request to login."""

    account: str
    password: str
    login_method: int = field(metadata=field_options(alias="loginMethod"))
    timestamp: str
    language: str = LANGUAGE
    country_code: int = field(
        metadata=field_options(alias="countryCode"), default=COUNTRY_CODE
    )
    browser: str = BROWSER
    equipment: int = EQUIPMENT

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class UserLoginResponse(BaseResponse):
    """Response from access token call."""

    token: str


@dataclass
class UserSmsLoginRequest(DataClassJSONMixin):
    """Request to login via sms."""

    telephone: str
    timestamp: str
    valid_code: str = field(metadata=field_options(alias="validCode"))
    # String like "1-{telephone}_validCode"
    valid_code_key: str = field(metadata=field_options(alias="validCodeKey"))

    country_code: int = field(
        metadata=field_options(alias="countryCode"), default=COUNTRY_CODE
    )
    browser: str = BROWSER
    equipment: int = EQUIPMENT

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UserPreAuthRequest(DataClassJSONMixin):
    """Request for pre-auth."""

    account: str


@dataclass
class UserPreAuthResponse(BaseResponse):
    """Response from pre-auth."""

    token: str = ""


@dataclass
class UserSendSmsRequest(DataClassJSONMixin):
    """Request to send SMS code."""

    telephone: str
    timestamp: str
    token: str
    sign: str
    nationcode: int = field(
        metadata=field_options(alias="nationcode"), default=COUNTRY_CODE
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UserSendSmsResponse(BaseResponse):
    """Response from send SMS."""

    valid_code_key: str = field(
        metadata=field_options(alias="validCodeKey"), default=""
    )


@dataclass(kw_only=True)
class UserSmsLoginResponse(BaseResponse):
    """Response from access token call."""

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
class FileListResponse(BaseResponse):
    """Response from file list call."""

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
class GetFileDownloadUrlResponse(BaseResponse):
    """Response from file download call."""

    url: str
