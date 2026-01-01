"""Equipment related API data models mirroring OpenAPI Spec.

The following endpoints are supported:
- /api/terminal/user/activateEquipment
- /api/terminal/user/bindEquipment
- /api/terminal/equipment/unlink
- /api/equipment/bind/status
- /api/equipment/query/by/equipmentno
- /api/equipment/manual/deleteApi
- /api/equipment/query/by/{userId}
"""

from dataclasses import dataclass, field
from typing import List

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseResponse, BooleanEnum


@dataclass
class ActivateEquipmentDTO(DataClassJSONMixin):
    """Request to activate equipment.

    Used by:
        /api/terminal/user/activateEquipment (POST)
    """

    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    """Device serial number."""
    """设备号."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class BindEquipmentDTO(DataClassJSONMixin):
    """Request to bind equipment.

    Used by:
        /api/terminal/user/bindEquipment (POST)
    """

    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    """Device serial number."""
    """设备号."""

    account: str
    """User account."""
    """账号."""

    name: str
    """Device name."""
    """设备名称."""

    total_capacity: str = field(metadata=field_options(alias="totalCapacity"))
    """Total device capacity."""
    """设备总容量."""

    flag: str | None = None
    """Identifier (Fixed value: 1)."""
    """标识（固定值：1）."""

    label: List[str] = field(default_factory=list)
    """Labels."""
    """标签页."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UnbindEquipmentDTO(DataClassJSONMixin):
    """Request to unbind equipment.

    Used by:
        /api/terminal/equipment/unlink (POST)
    """

    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    """Device serial number."""
    """设备号."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class QueryEquipmentDTO(DataClassJSONMixin):
    """Request to query equipment list.

    Used by:
        /api/equipment/query/user/equipment/deleteApi (POST)
    """

    page_no: str = field(metadata=field_options(alias="pageNo"))
    """页码."""

    page_size: str = field(metadata=field_options(alias="pageSize"))
    """每页显示的个数."""

    equipment_number: str | None = field(
        metadata=field_options(alias="equipmentNumber"), default=None
    )
    """设备号."""

    firmware_version: str | None = field(
        metadata=field_options(alias="firmwareVersion"), default=None
    )
    """固件版本号."""

    country_code: str | None = field(
        metadata=field_options(alias="countryCode"), default=None
    )
    """国家码."""

    telephone: str | None = field(default=None)
    """手机号."""

    email: str | None = field(default=None)
    """邮箱."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class UserEquipmentDTO(DataClassJSONMixin):
    """Request to query user equipment.

    Used by:
        /api/equipment/query/by/equipmentno (POST)
    """

    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    """Device serial number."""
    """设备号."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class EquipmentManualDTO(DataClassJSONMixin):
    """Request for equipment manual.

    Used by:
        /api/equipment/manual/deleteApi (POST)
    """

    equipment_no: str = field(metadata=field_options(alias="equipmentNo"))
    """Device serial number."""
    """设备号."""

    language: str
    """Language (JP, CN, HK, EN)."""
    """语言-JP、CN、HK、EN."""

    logic_version: str = field(metadata=field_options(alias="logicVersion"))
    """Logic version number."""
    """逻辑版本号."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class BindStatusVO(BaseResponse):
    """Response for bind status.

    Used by:
        /api/equipment/bind/status (POST)
    """

    bind_status: bool | None = field(
        metadata=field_options(alias="bindStatus"), default=None
    )
    """绑定状态(true:绑定；false:未绑定)."""
    """Bind status (true: bound, false: unbound)."""


@dataclass(kw_only=True)
class EquipmentManualVO(BaseResponse):
    """Response for equipment manual.

    Used by:
        /api/equipment/manual/deleteApi (POST)
    """

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    url: str | None = None
    md5: str | None = None
    file_name: str | None = field(
        metadata=field_options(alias="fileName"), default=None
    )
    version: str | None = None


@dataclass
class EquipmentVO(DataClassJSONMixin):
    """Equipment details object."""

    equipment_number: str | None = field(
        metadata=field_options(alias="equipmentNumber"), default=None
    )
    firmware_version: str | None = field(
        metadata=field_options(alias="firmwareVersion"), default=None
    )
    update_status: str | None = field(
        metadata=field_options(alias="updateStatus"), default=None
    )
    remark: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class UserEquipmentVO(BaseResponse):
    """User equipment details response.

    Used by:
        /api/equipment/query/by/equipmentno (POST)
    """

    equipment_number: str | None = field(
        metadata=field_options(alias="equipmentNumber"), default=None
    )
    user_id: int | None = field(metadata=field_options(alias="userId"), default=None)
    name: str | None = None
    status: str | None = None


@dataclass(kw_only=True)
class UserEquipmentListVO(BaseResponse):
    """List of user equipment.

    Used by:
        /api/equipment/query/by/{userId} (GET)
    """

    equipment_vo_list: List[UserEquipmentVO] = field(
        metadata=field_options(alias="equipmentVOList"), default_factory=list
    )


@dataclass
class QueryEquipmentVO(DataClassJSONMixin):
    """Detailed equipment query response object."""

    user_id: str | None = field(metadata=field_options(alias="userId"), default=None)
    equipment_number: str | None = field(
        metadata=field_options(alias="equipmentNumber"), default=None
    )
    name: str | None = None
    firmware_version: str | None = field(
        metadata=field_options(alias="firmwareVersion"), default=None
    )
    create_time: int | None = field(
        metadata=field_options(alias="createTime"), default=None
    )
    activate_time: int | None = field(
        metadata=field_options(alias="activateTime"), default=None
    )
    country_code: str | None = field(
        metadata=field_options(alias="countryCode"), default=None
    )
    telephone: str | None = None
    email: str | None = None
    status: BooleanEnum | None = None
    """Device status (e.g., Y: Active, N: Inactive)."""

    update_status: str | None = field(
        metadata=field_options(alias="updateStatus"), default=None
    )
    """Firmware update status."""

    remark: str | None = None
    """Remark or note."""
    file_server: str | None = field(
        metadata=field_options(alias="fileServer"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True
