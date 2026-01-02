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

    account: str
    """User account."""

    name: str
    """Device name."""

    total_capacity: str = field(metadata=field_options(alias="totalCapacity"))
    """Total device capacity."""

    flag: str | None = None
    """Identifier (Fixed value: 1)."""

    label: list[str] = field(default_factory=list)
    """Labels."""

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

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class QueryEquipmentDTO(DataClassJSONMixin):
    """Request to query equipment list.

    Used by:
        /api/equipment/query/user/equipment/deleteApi (POST)
    """

    page_no: str = field(metadata=field_options(alias="pageNo"))
    """Page number."""

    page_size: str = field(metadata=field_options(alias="pageSize"))
    """Page size."""

    equipment_number: str | None = field(
        metadata=field_options(alias="equipmentNumber"), default=None
    )
    """Equipment number."""

    firmware_version: str | None = field(
        metadata=field_options(alias="firmwareVersion"), default=None
    )
    """Firmware version."""

    country_code: str | None = field(
        metadata=field_options(alias="countryCode"), default=None
    )
    """Country code."""

    telephone: str | None = field(default=None)
    """Telephone."""

    email: str | None = field(default=None)
    """Email."""

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

    language: str
    """Language (JP, CN, HK, EN)."""

    logic_version: str = field(metadata=field_options(alias="logicVersion"))
    """Logic version number."""

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

    equipment_vo_list: list[UserEquipmentVO] = field(
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
