from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.config import TO_DICT_ADD_OMIT_NONE_FLAG, BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseResponse


@dataclass
class BindEquipmentRequest(DataClassJSONMixin):
    account: str
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    flag: str | None = None
    name: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UnlinkRequest(DataClassJSONMixin):
    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    version: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UserCheckRequest(DataClassJSONMixin):
    email: str

    # Not currently using any of these fields, but they exist in the request
    country_code: str = field(metadata=field_options(alias="countryCode"), default="")
    telephone: str = ""
    user_name: str = field(metadata=field_options(alias="userName"), default="")
    domain: str = ""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class RandomCodeRequest(DataClassJSONMixin):
    account: str
    version: str | None = None
    country_code: str | None = field(
        metadata=field_options(alias="countryCode"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class RandomCodeResponse(BaseResponse):
    random_code: str | None = field(
        metadata=field_options(alias="randomCode"), default=None
    )
    timestamp: str | None = None


@dataclass
class LoginRequest(DataClassJSONMixin):
    account: str
    password: str
    country_code: str | None = field(
        metadata=field_options(alias="countryCode"), default=None
    )
    browser: str | None = None
    equipment: int | None = None
    login_method: str | None = field(
        metadata=field_options(alias="loginMethod"), default=None
    )
    language: str | None = None
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    timestamp: str | None = None


@dataclass
class LoginResponse(BaseResponse):
    token: str | None = None
    user_name: str | None = field(
        metadata=field_options(alias="userName"), default=None
    )
    is_bind: str = field(metadata=field_options(alias="isBind"), default="N")
    is_bind_equipment: str = field(
        metadata=field_options(alias="isBindEquipment"), default="N"
    )
    sold_out_count: int = field(metadata=field_options(alias="soldOutCount"), default=0)


@dataclass
class LoginResult(DataClassJSONMixin):
    """Login result object which is returned by the User Service."""

    token: str
    is_bind: str
    is_bind_equipment: str


@dataclass
class UserVO(DataClassJSONMixin):
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
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class UserQueryResponse(BaseResponse):
    user: UserVO | None = None
    is_user: bool = field(metadata=field_options(alias="isUser"), default=False)
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
