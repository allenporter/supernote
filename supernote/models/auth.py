"""Module for authentication API data models.

The following endpoints are supported:
- /official/user/account/login/equipment
- /official/user/account/login/new
- /official/user/query/random/code
- /official/user/sms/login
- /user/sms/validcode/send
- /user/query/token
- /user/validcode/pre-auth
- /user/logout (empty body)
"""

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
class LoginDTO(DataClassJSONMixin):
    """Request to login.

    This is used by the following POST endpoints:
        /official/user/account/login/equipment
        /official/user/account/login/new
    """

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
class LoginVO(BaseResponse):
    """Response from login endpoints."""

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
class RandomCodeDTO(DataClassJSONMixin):
    """Request to get a random code.

    This is used by the following POST endpoint:
        /official/user/query/random/code
    """

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


@dataclass(kw_only=True)
class RandomCodeVO(BaseResponse):
    """Response from random code endpoint."""

    random_code: str = field(metadata=field_options(alias="randomCode"), default="")
    timestamp: str = ""


@dataclass
class QueryTokenDTO(DataClassJSONMixin):
    """Request to token endpoint.

    This is used by the following POST endpoint:
        /user/query/token
    """


@dataclass(kw_only=True)
class QueryTokenVO(BaseResponse):
    """Response from token endpoint."""


class OSType(str, BaseEnum):
    """OS Type."""

    WINDOWS = "WINDOWS"
    MACOS = "MACOS"
    LINUX = "LINUX"
    ANDROID = "ANDROID"
    IOS = "IOS"


@dataclass
class SmsLoginDTO(DataClassJSONMixin):
    """Request to login via sms.

    This is used by the following POST endpoint:
        /user/sms/login
    """

    valid_code: str = field(metadata=field_options(alias="validCode"))
    """SMS/Email verification code."""

    valid_code_key: str = field(metadata=field_options(alias="validCodeKey"))
    """Session key for validation code."""

    country_code: int = field(
        metadata=field_options(alias="countryCode"), default=COUNTRY_CODE
    )

    telephone: str | None = None
    """User phone number."""

    timestamp: str | None = None
    """Client timestamp."""

    email: str | None = None
    """User email."""

    browser: str = BROWSER
    """Browser name (user agent info)."""

    equipment: Equipment = Equipment.WEB
    """Device type."""

    devices: OSType | None = OSType.WINDOWS
    """OS Type."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class SmsLoginVO(BaseResponse):
    """Response from access token call."""

    token: str


@dataclass
class UserPreAuthRequest(DataClassJSONMixin):
    """Request for pre-auth.

    This is used by the following POST endpoint:
        /user/validcode/pre-auth
    """

    account: str


@dataclass
class UserPreAuthResponse(BaseResponse):
    """Response from pre-auth."""

    token: str = ""


@dataclass
class SendSmsDTO(DataClassJSONMixin):
    """Request to send SMS code.

    This is used by the following POST endpoint:
        /user/sms/validcode/send
    """

    telephone: str
    timestamp: str
    token: str
    sign: str
    extend: str | None = None
    nationcode: int = field(
        metadata=field_options(alias="nationcode"), default=COUNTRY_CODE
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SendSmsVO(BaseResponse):
    """Response from send SMS."""

    valid_code_key: str = field(
        metadata=field_options(alias="validCodeKey"), default=""
    )
