"""Module for authentication API data models.

The following endpoints are supported:
- /api/official/user/account/login/equipment
- /api/official/user/account/login/new
- /api/official/user/query/random/code
- /api/official/user/sms/login
- /api/user/sms/validcode/send
- /api/user/query/token
- /api/user/validcode/pre-auth
- /api/user/logout (empty body)
"""

from dataclasses import dataclass, field

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


def _deserialize_int_equipment(value: str) -> Equipment:
    return Equipment(int(value))


@dataclass
class UserCheckDTO(DataClassJSONMixin):
    """Request to check user existence."""

    email: str
    country_code: str = field(metadata=field_options(alias="countryCode"), default="")
    telephone: str = ""
    user_name: str = field(metadata=field_options(alias="userName"), default="")
    domain: str = ""

    class Config(BaseConfig):
        serialize_by_alias = True


class LoginMethod(str, BaseEnum):
    """Method for logging in to account."""

    PHONE = "1"
    EMAIL = "2"
    WECHAT = "3"


@dataclass
class LoginDTO(DataClassJSONMixin):
    """Request to login.

    This is used by the following POST endpoints:
        /api/official/user/account/login/equipment
        /api/official/user/account/login/new
    """

    account: str
    """User account (must be an email address)."""

    password: str
    """Hashed password. Schema: SHA256(MD5(pwd) + randomCode)) or MD5(pwd + randomCode)."""

    timestamp: str
    """Client timestamp in milliseconds."""

    login_method: LoginMethod = field(metadata=field_options(alias="loginMethod"))
    """Login method."""

    language: str = LANGUAGE
    """Language code."""

    country_code: int | None = field(
        metadata=field_options(alias="countryCode"), default=None
    )
    """Country code."""

    browser: str = BROWSER
    """Browser name (user agent info)."""

    equipment: Equipment = field(
        metadata=field_options(deserialize=_deserialize_int_equipment),
        default=Equipment.WEB,
    )
    """Device type."""

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    """Device serial number (SN12345678) or other client identifier (WEB)."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class LoginVO(BaseResponse):
    """Response from login endpoints."""

    token: str
    """JWT Access Token."""

    counts: str
    """Error count."""

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
        /api/official/user/query/random/code
    """

    account: str
    """User account (must be an email address)."""

    country_code: int | None = field(
        metadata=field_options(alias="countryCode"), default=None
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
    """Server-side nonce (salt) used for password hashing."""

    timestamp: str = ""
    """Client timestamp in milliseconds."""


@dataclass
class QueryTokenDTO(DataClassJSONMixin):
    """Request to token endpoint.

    This is used by the following POST endpoint:
        /api/user/query/token
    """


@dataclass(kw_only=True)
class QueryTokenVO(BaseResponse):
    """Response from token endpoint."""

    token: str | None = None
    """JWT Access Token."""

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = False
        code_generation_options = ["TO_DICT_ADD_OMIT_NONE_FLAG"]


class OSType(str, BaseEnum):
    """OS Type."""

    WINDOWS = "WINDOWS"
    MACOS = "MACOS"
    LINUX = "LINUX"
    ANDROID = "ANDROID"
    IOS = "IOS"


@dataclass
class UserVO(DataClassJSONMixin):
    """User profile VO."""

    user_name: str | None = field(
        metadata=field_options(alias="userName"), default=None
    )
    email: str | None = None
    phone: str | None = None
    country_code: str | None = field(
        metadata=field_options(alias="countryCode"), default=None
    )
    total_capacity: str = field(
        metadata=field_options(alias="totalCapacity"), default="0"
    )
    file_server: str = field(metadata=field_options(alias="fileServer"), default="0")
    avatars_url: str | None = field(
        metadata=field_options(alias="avatarsUrl"), default=None
    )
    birthday: str | None = None
    sex: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = ["TO_DICT_ADD_OMIT_NONE_FLAG"]


@dataclass
class UserQueryByIdVO(BaseResponse):
    """User query response."""

    user: UserVO | None = None
    is_user: bool = field(metadata=field_options(alias="isUser"), default=False)
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )


@dataclass
class SmsLoginDTO(DataClassJSONMixin):
    """Request to login via sms.

    This is used by the following POST endpoint:
        /api/user/sms/login
    """

    valid_code: str = field(metadata=field_options(alias="validCode"))
    """SMS/Email verification code."""

    valid_code_key: str = field(metadata=field_options(alias="validCodeKey"))
    """Redis session key for the code (e.g., '{email}_validCode')."""

    country_code: int = field(
        metadata=field_options(alias="countryCode"), default=COUNTRY_CODE
    )

    telephone: str | None = None
    """User phone number."""

    timestamp: str | None = None
    """Client timestamp in milliseconds."""

    email: str | None = None
    """User email."""

    browser: str = BROWSER
    """Browser name (user agent info)."""

    equipment: Equipment = Equipment.WEB
    """Device type."""

    devices: OSType | None = OSType.WINDOWS
    """OS Type: WINDOWS, MACOS, LINUX, ANDROID, IOS."""

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
        /api/user/validcode/pre-auth
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
        /api/user/sms/validcode/send
    """

    telephone: str
    """User phone number."""

    timestamp: str
    """Client timestamp in milliseconds."""

    token: str
    """JWT Access Token."""

    sign: str
    """JWT Signature."""

    extend: str | None = None
    """JWT Extension."""

    nationcode: int = field(
        metadata=field_options(alias="nationcode"), default=COUNTRY_CODE
    )
    """Country code."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SendSmsVO(BaseResponse):
    """Response from send SMS."""

    valid_code_key: str = field(
        metadata=field_options(alias="validCodeKey"), default=""
    )


@dataclass
class EmailDTO(DataClassJSONMixin):
    """Request to send email code.

    Used by:
        /api/user/mail/validcode (POST)
    """

    email: str
    """User email."""

    language: str | None = None
    """Language code."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ValidCodeDTO(DataClassJSONMixin):
    """Request to check validation code.

    Used by:
        /api/user/check/validcode (POST)
    """

    valid_code_key: str = field(metadata=field_options(alias="validCodeKey"))
    """Key for the validation code."""

    valid_code: str = field(metadata=field_options(alias="validCode"))
    """The validation code."""

    class Config(BaseConfig):
        serialize_by_alias = True
