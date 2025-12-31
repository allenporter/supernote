"""Module for authentication API models."""

from dataclasses import dataclass, field
from enum import Enum

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseEnum, BaseResponse

COUNTRY_CODE = 1
BROWSER = "Chrome142"
LANGUAGE = "en"


class Equipment(BaseEnum):
    """Device type."""

    WEB = 1
    APP = 2
    TERMINAL = 3
    USER_PLATFORM = 4


class LoginMethod(Enum):
    """Method for logging in to account."""

    PHONE = 1
    EMAIL = 2
    WECHAT = 3


@dataclass
class UserLoginRequest(DataClassJSONMixin):
    """Request to login."""

    account: str
    """User account (email, username, phone number etc)."""

    password: str
    """Password (SHA-256 encrypted using random code)."""

    timestamp: str
    """Client timestamp."""

    login_method: LoginMethod = field(metadata=field_options(alias="loginMethod"))
    """Login method."""

    language: str = LANGUAGE
    """Language code."""

    country_code: int = field(
        metadata=field_options(alias="countryCode"), default=COUNTRY_CODE
    )
    """Country code."""

    browser: str = BROWSER
    """Browser name (user agent info)."""

    equipment: Equipment = Equipment.WEB
    """Device type."""

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    """Device serial number (Required for Terminal login)."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class UserLoginResponse(BaseResponse):
    """Response from access token call."""

    token: str
    """JWT Access Token."""

    user_name: str | None = field(
        metadata=field_options(alias="userName"), default=None
    )
    """User nickname."""

    is_bind: str = field(metadata=field_options(alias="isBind"), default="N")
    """Is account bound."""

    is_bind_equipment: str = field(
        metadata=field_options(alias="isBindEquipment"), default="N"
    )
    """Is device bound (Terminal only)."""

    sold_out_count: int = field(metadata=field_options(alias="soldOutCount"), default=0)
    """Logout count."""


@dataclass
class UserRandomCodeRequest(DataClassJSONMixin):
    """Request to get a random code."""

    account: str
    """User account (email, username, phone number etc)."""

    country_code: int = field(
        metadata=field_options(alias="countryCode"), default=COUNTRY_CODE
    )
    """Country code."""

    version: str | None = None
    """Version."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UserRandomCodeResponse(BaseResponse):
    """Response from login."""

    random_code: str = field(metadata=field_options(alias="randomCode"), default="")
    timestamp: str = ""


@dataclass
class TokenRequest(DataClassJSONMixin):
    """Request to token endpoint."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class TokenResponse(BaseResponse):
    """Response from token endpoint."""


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
    """User ID."""

    user_name: str = field(metadata=field_options(alias="userName"))
    """User nickname."""

    birthday: str = field(metadata=field_options(alias="birthday"))
    """User birthday."""

    country_code: str = field(
        metadata=field_options(alias="countryCode"), default=str(COUNTRY_CODE)
    )
    """Country code."""

    telephone: str = field(metadata=field_options(alias="telephone"), default="")
    """User phone number."""

    sex: str = ""
    """User sex."""

    file_server: str = field(metadata=field_options(alias="fileServer"), default="")
    """User assigned file server url."""


@dataclass
class UserSmsLoginRequest(DataClassJSONMixin):
    """Request to login via sms."""

    telephone: str
    """User phone number."""

    timestamp: str
    """Client timestamp."""

    valid_code: str = field(metadata=field_options(alias="validCode"))
    """SMS/Email verification code."""

    valid_code_key: str = field(metadata=field_options(alias="validCodeKey"))
    """Session key for validation code."""

    country_code: int = field(
        metadata=field_options(alias="countryCode"), default=COUNTRY_CODE
    )

    browser: str = BROWSER
    """Browser name (user agent info)."""

    equipment: Equipment = Equipment.WEB
    """Device type."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class UserSmsLoginResponse(BaseResponse):
    """Response from access token call."""

    token: str


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
