from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.mixins.json import DataClassJSONMixin
from mashumaro.config import BaseConfig, TO_DICT_ADD_OMIT_NONE_FLAG
from .base import BaseResponse


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
class RandomCodeResponse(BaseResponse):
    random_code: str | None = field(
        metadata=field_options(alias="randomCode"), default=None
    )
    timestamp: str | None = None


@dataclass
class LoginRequest(DataClassJSONMixin):
    account: str
    password: str
    countryCode: str | None = None
    browser: str | None = None
    equipment: int | None = None
    loginMethod: str | None = None
    language: str | None = None
    equipmentNo: str | None = None
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
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]


@dataclass
class UserQueryResponse(BaseResponse):
    user: UserVO | None = None
    is_user: bool = field(metadata=field_options(alias="isUser"), default=False)
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
