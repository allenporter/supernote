"""Data models for user related API calls.

The following endpoints are supported:
- /api/official/user/check/exists/server (POST)
- /api/user/check/exists (POST)
- /api/user/query/info (POST)
- /api/user/update (POST)
- /api/user/update/name (POST)

"""

from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseEnum, BaseResponse

DEFAULT_COUNTRY_CODE = 1


@dataclass
class UserCheckDTO(DataClassJSONMixin):
    """Request to check if user exists.

    Used by:
        /api/official/user/check/exists/server (POST)
        /api/user/check/exists (POST)
    """

    country_code: str | None = field(
        metadata=field_options(alias="countryCode"), default=None
    )
    telephone: str | None = None
    email: str | None = None
    user_name: str | None = field(
        metadata=field_options(alias="userName"), default=None
    )
    domain: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class UserCheckVO(BaseResponse):
    """Response for user check.

    Used by:
        /api/official/user/check/exists/server (POST)
    """

    dms: str | None = None
    """Data Management System (regional server center identifier, e.g., "ALL", "CN", "US")."""

    user_id: int | None = field(metadata=field_options(alias="userId"), default=None)
    """User ID."""

    unique_machine_id: str | None = field(
        metadata=field_options(alias="uniqueMachineId"), default=None
    )
    """Server-side generated unique identifier for the machine instance."""


@dataclass
class UserQueryDTO(DataClassJSONMixin):
    """Request to query user.

    Used by:
        /api/user/query/info (POST)
    """

    country_code: str | None = field(
        metadata=field_options(alias="countryCode"), default=None
    )
    """Country code."""

    value: str | None = None
    """Search query."""

    token: str | None = None
    """User token."""

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    """Equipment number."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UserUpdateDTO(DataClassJSONMixin):
    """Request to update user info.

    Used by:
        /api/user/update (POST)
    """

    sex: str | None = None
    """Gender."""

    birthday: str | None = None
    """Format: YYYY-MM-DD."""

    personal_sign: str | None = field(
        metadata=field_options(alias="personalSign"), default=None
    )
    """Personal signature."""

    hobby: str | None = None
    """Hobby."""

    address: str | None = None
    """Address."""

    job: str | None = None
    """Job."""

    education: str | None = None
    """Education."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UpdateUserNameDTO(DataClassJSONMixin):
    """Request to update user name.

    Used by:
        /api/user/update/name (POST)
    """

    user_name: str = field(metadata=field_options(alias="userName"))
    """New nickname."""

    class Config(BaseConfig):
        serialize_by_alias = True


class IsNormalUser(str, BaseEnum):
    """User status."""

    NORMAL = "Y"
    FROZEN = "N"
    ADMIN = "A"


@dataclass(kw_only=True)
class UserVO(BaseResponse):
    """Data object describing user information."""

    user_id: str | None = field(metadata=field_options(alias="userId"), default=None)
    """User ID."""

    user_name: str | None = field(
        metadata=field_options(alias="userName"), default=None
    )
    """User nickname."""

    country_code: str | None = field(
        metadata=field_options(alias="countryCode"), default=None
    )
    """Country code."""

    telephone: str | None = None
    """Telephone number."""

    email: str | None = None
    """Email address."""

    wechat_no: str | None = field(
        metadata=field_options(alias="wechatNo"), default=None
    )
    """WeChat number."""

    sex: str | None = None
    """Gender."""

    birthday: str | None = None
    """Format: YYYY-MM-DD."""

    personal_sign: str | None = field(
        metadata=field_options(alias="personalSign"), default=None
    )
    """Personal signature."""

    hobby: str | None = None
    """Hobby."""

    education: str | None = None
    """Education."""

    job: str | None = None
    """Job."""

    address: str | None = None
    """Address."""

    create_time: str | None = field(
        metadata=field_options(alias="createTime"), default=None
    )
    """User creation time."""

    is_normal: IsNormalUser | None = field(
        metadata=field_options(alias="isNormal"), default=IsNormalUser.NORMAL
    )
    """User status."""

    file_server: str | None = field(
        metadata=field_options(alias="fileServer"), default=None
    )
    """Storage provider code ('0': ufile, '1': aws) or private cloud URL."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UserInfo(DataClassJSONMixin):
    """Refined user information object."""

    user_id: int | None = field(metadata=field_options(alias="userId"), default=None)
    """User ID."""

    user_name: str | None = field(
        metadata=field_options(alias="userName"), default=None
    )
    """User nickname."""

    country_code: str | None = field(
        metadata=field_options(alias="countryCode"), default=None
    )
    """Country code."""

    phone: str | None = None
    """Phone number."""

    email: str | None = None
    """Email address."""

    sex: str | None = None
    """Gender."""

    birthday: str | None = None
    """Format: YYYY-MM-DD."""

    personal_sign: str | None = field(
        metadata=field_options(alias="personalSign"), default=None
    )
    """Personal signature."""

    hobby: str | None = None
    """Hobby."""

    education: str | None = None
    """Education."""

    job: str | None = None
    """Job."""

    address: str | None = None
    """Address."""

    avatars_url: str | None = field(
        metadata=field_options(alias="avatarsUrl"), default=None
    )
    """Avatar URL."""

    total_capacity: str | None = field(
        metadata=field_options(alias="totalCapacity"), default=None
    )
    """Total storage capacity."""

    file_server: str | None = field(
        metadata=field_options(alias="fileServer"), default=None
    )
    """Storage provider code ('0': ufile, '1': aws) or private cloud URL."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class UserQueryVO(BaseResponse):
    """Response for user query info.

    Used by:
        /api/user/query/info (POST)
    """

    user: UserInfo | None = None
    """User information."""

    is_user: bool | None = field(metadata=field_options(alias="isUser"), default=None)
    """Whether it's a user."""

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    """Equipment number."""


@dataclass(kw_only=True)
class UserQueryByIdVO(BaseResponse):
    """Response for user query by ID.

    Used by:
        /api/user/query (POST)
        /api/user/query/user/{userId} (GET)
    """

    user_id: int | None = field(metadata=field_options(alias="userId"), default=None)
    """User ID."""

    user_name: str | None = field(
        metadata=field_options(alias="userName"), default=None
    )
    """User nickname."""

    country_code: str | None = field(
        metadata=field_options(alias="countryCode"), default=None
    )
    """Country code."""

    telephone: str | None = None
    """Telephone number."""

    email: str | None = None
    """Email address."""

    sex: str | None = None
    """Gender."""

    birthday: str | None = None
    """Format: YYYY-MM-DD."""

    personal_sign: str | None = field(
        metadata=field_options(alias="personalSign"), default=None
    )
    """Personal signature."""

    hobby: str | None = None
    """Hobby."""

    education: str | None = None
    """Education."""

    job: str | None = None
    """Job."""

    address: str | None = None
    """Address."""

    avatars_url: str | None = field(
        metadata=field_options(alias="avatarsUrl"), default=None
    )
    """Avatar URL."""

    total_capacity: str | None = field(
        metadata=field_options(alias="totalCapacity"), default=None
    )
    """Total storage capacity."""

    file_server: str | None = field(
        metadata=field_options(alias="fileServer"), default=None
    )
    """Assigned file server URL."""

    is_normal: IsNormalUser | None = field(
        metadata=field_options(alias="isNormal"), default=None
    )
    """User status."""


@dataclass
class UserDTO(DataClassJSONMixin):
    """Request for querying all users.

    Used by:
        /api/user/query/all (POST)
    """

    page_no: str = field(metadata=field_options(alias="pageNo"))
    """Page number."""

    page_size: str = field(metadata=field_options(alias="pageSize"))
    """Number of users per page."""

    user_name: str | None = field(
        metadata=field_options(alias="userName"), default=None
    )
    """User nickname."""

    telephone: str | None = None
    """Telephone number."""

    email: str | None = None
    """Email address."""

    is_normal: IsNormalUser | None = field(
        metadata=field_options(alias="isNormal"), default=None
    )
    """User status."""

    create_time_start: str | None = field(
        metadata=field_options(alias="createTimeStart"), default=None
    )
    """User creation time start."""

    create_time_end: str | None = field(
        metadata=field_options(alias="createTimeEnd"), default=None
    )
    """User creation time end."""

    file_server: str | None = field(
        metadata=field_options(alias="fileServer"), default=None
    )
    """Assigned file server URL."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FreezeOrUnfreezeUserDTO(DataClassJSONMixin):
    """Request to freeze or unfreeze user.

    Used by:
        /api/user/freeze (PUT)
    """

    user_id: str = field(metadata=field_options(alias="userId"))
    """User ID."""

    flag: str = field(default="Y")
    """Y: Freeze, N: Unfreeze."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UserInfoDTO(DataClassJSONMixin):
    """Request for user info.

    Used by:
        /api/user/query/one (POST)
    """

    country_code: str | None = field(
        metadata=field_options(alias="countryCode"), default=None
    )
    """Country code."""

    telephone: str | None = None
    """Telephone number."""

    email: str | None = None
    """Email address."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UserRegisterDTO(DataClassJSONMixin):
    """Request to register a new user.

    Used by:
        /api/user/register (POST)
    """

    email: str
    """Email address."""

    password: str
    """Md5 hash of password."""

    user_name: str | None = field(
        metadata=field_options(alias="userName"), default=None
    )
    """User nickname (used for display)."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class RetrievePasswordDTO(DataClassJSONMixin):
    """Request to retrieve password.

    Used by:
        /api/official/user/retrieve/password (POST)
    """

    password: str
    """New password (md5 hash)."""

    telephone: str | None = None
    """Telephone number."""

    email: str | None = None
    """Email address."""

    country_code: str | None = field(
        metadata=field_options(alias="countryCode"), default=None
    )
    """Country code."""

    version: str | None = None
    """Version."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UpdatePasswordDTO(DataClassJSONMixin):
    """Request to update password.

    Used by:
        /api/user/password (PUT)
    """

    password: str
    """New password (md5 hash)."""

    version: str | None = None
    """Version."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UpdateEmailDTO(DataClassJSONMixin):
    """Request to update email.

    Used by:
        /api/user/email (PUT)
    """

    email: str
    """New email address."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class LoginRecordDTO(DataClassJSONMixin):
    """Request to query login records.

    Used by:
        /api/user/query/loginRecord (POST)
    """

    page_no: str = field(metadata=field_options(alias="pageNo"))
    """Page number."""

    page_size: str = field(metadata=field_options(alias="pageSize"))
    """Page size."""

    telephone: str | None = None
    """Telephone number."""

    email: str | None = None
    """Email address."""
    login_method: str | None = field(
        metadata=field_options(alias="loginMethod"), default=None
    )
    """1: Phone, 2: Email, 3: WeChat"""

    equipment: str | None = None
    """1: Web, 2: App, 3: Terminal, 4: Platform"""

    create_time_start: str | None = field(
        metadata=field_options(alias="createTimeStart"), default=None
    )
    """Start time."""

    create_time_end: str | None = field(
        metadata=field_options(alias="createTimeEnd"), default=None
    )
    """End time."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class LoginRecordVO(DataClassJSONMixin):
    """Login record response item."""

    user_id: str | None = field(metadata=field_options(alias="userId"), default=None)
    """User ID."""

    user_name: str | None = field(
        metadata=field_options(alias="userName"), default=None
    )
    """User nickname."""

    create_time: str | None = field(
        metadata=field_options(alias="createTime"), default=None
    )
    """Creation time."""

    telephone: str | None = None
    """Telephone number."""

    email: str | None = None
    """Email address."""

    wechat_no: str | None = field(
        metadata=field_options(alias="wechatNo"), default=None
    )
    """WeChat number."""

    browser: str | None = None
    """Browser info."""

    equipment: str | None = None
    """Equipment info."""

    ip: str | None = None
    """IP address."""

    login_method: str | None = field(
        metadata=field_options(alias="loginMethod"), default=None
    )
    """Login method."""

    class Config(BaseConfig):
        serialize_by_alias = True
