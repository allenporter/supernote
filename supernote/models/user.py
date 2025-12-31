"""Data models for user related API calls.

The following endpoints are supported:
- /official/user/check/exists/server (POST)
- /user/check/exists (POST)
- /user/query/info (POST)
- /user/update (POST)
- /user/update/name (POST)

"""

from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseResponse, BooleanEnum

DEFAULT_COUNTRY_CODE = 1


@dataclass
class UserCheckDTO(DataClassJSONMixin):
    """Request to check if user exists.

    Used by:
        /official/user/check/exists/server (POST)
        /user/check/exists (POST)
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
        /official/user/check/exists/server (POST)
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
        /user/query/info (POST)
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
        /user/update (POST)
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
        /user/update/name (POST)
    """

    user_name: str = field(metadata=field_options(alias="userName"))
    """New nickname."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UserVO(DataClassJSONMixin):
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

    is_normal: BooleanEnum | None = field(
        metadata=field_options(alias="isNormal"), default=None
    )
    """Whether the user is normal."""

    file_server: str | None = field(
        metadata=field_options(alias="fileServer"), default=None
    )
    """Assigned file server URL."""

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
    """Assigned file server URL."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class UserQueryVO(BaseResponse):
    """Response for user query info.

    Used by:
        /user/query/info (POST)
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
        /user/query (POST)
        /user/query/user/{userId} (GET)
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

    is_normal: str | None = field(
        metadata=field_options(alias="isNormal"), default=None
    )
    """Whether the user is normal."""


@dataclass
class UserDTO(DataClassJSONMixin):
    """Request for querying all users.

    Used by:
        /user/query/all (POST)
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

    is_normal: str | None = field(
        metadata=field_options(alias="isNormal"), default=None
    )
    """Whether the user is normal."""

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
        /user/freeze (PUT)
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
        /user/query/one (POST)
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
