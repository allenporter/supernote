"""Wire models for the server component configuration API.

Shared by the `config` server component (`supernote.server.components.config`)
and `supernote.client.config.ConfigClient`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from mashumaro import field_options
from mashumaro.config import TO_DICT_ADD_OMIT_NONE_FLAG, BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseResponse

__all__ = [
    "ComponentConfigSource",
    "ComponentFieldSpecVO",
    "ComponentFieldType",
    "ComponentListResponseVO",
    "ComponentStatusResponseVO",
    "ComponentStatusVO",
    "ServerFeaturesVO",
    "UpdateComponentConfigDTO",
]


class ComponentConfigSource(StrEnum):
    """Origin tier for a component's effective configuration."""

    ENV = "env"
    YAML = "yaml"
    DATABASE = "database"
    DEFAULT = "default"

    @property
    def is_static(self) -> bool:
        """Whether this tier comes from static startup configuration (`env` or `yaml`)."""
        return self in (ComponentConfigSource.ENV, ComponentConfigSource.YAML)


class ComponentFieldType(StrEnum):
    """Normalized UI field type for a component configuration field."""

    BOOLEAN = "boolean"
    INTEGER = "integer"
    NUMBER = "number"
    STRING = "string"
    ARRAY = "array"
    OBJECT = "object"

    @classmethod
    def from_type_annotation(cls, type_repr: str) -> ComponentFieldType:
        """Map a Python type annotation string to a normalized UI field type."""
        lowered = type_repr.lower()
        if "bool" in lowered:
            return cls.BOOLEAN
        if "list" in lowered or "sequence" in lowered or "tuple" in lowered:
            return cls.ARRAY
        if "dict" in lowered or "mapping" in lowered:
            return cls.OBJECT
        if "float" in lowered:
            return cls.NUMBER
        if re.search(r"\bint\b", lowered):
            return cls.INTEGER
        return cls.STRING


@dataclass
class ComponentFieldSpecVO(DataClassJSONMixin):
    """Schema metadata for a single configuration field of a built-in component."""

    name: str
    """Field name in the component configuration dictionary."""

    type: ComponentFieldType
    """Normalized field type (`BOOLEAN`, `INTEGER`, `NUMBER`, `STRING`, `ARRAY`, `OBJECT`)."""

    default: Any = None
    """Default value when unset."""

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class ComponentStatusVO(DataClassJSONMixin):
    """Effective runtime status and configuration provenance for a built-in component."""

    domain: str
    """Component domain identifier (e.g. `'webhooks'`, `'wiki'`, `'mcp'`)."""

    enabled: bool
    """Whether the component is configured as enabled."""

    running: bool
    """Whether the component is currently active in `ComponentLoader`."""

    source: ComponentConfigSource
    """Configuration source tier (`ENV`, `YAML`, `DATABASE`, or `DEFAULT`)."""

    read_only: bool = field(metadata=field_options(alias="readOnly"))
    """Whether dynamic edits are blocked (e.g. pinned by `env` or `yaml`)."""

    runtime_configurable: bool = field(
        metadata=field_options(alias="runtimeConfigurable")
    )
    """Whether changes apply live without a server restart."""

    restart_required: bool = field(
        default=False,
        metadata=field_options(alias="restartRequired"),
    )
    """Whether the component's persisted enabled state differs from its running state."""

    config: dict[str, Any] = field(default_factory=dict)
    """Effective component configuration dictionary."""

    fields: list[ComponentFieldSpecVO] = field(default_factory=list)
    """Declarative field descriptors extracted from the component's config schema."""

    field_sources: dict[str, ComponentConfigSource] = field(
        default_factory=dict,
        metadata=field_options(alias="fieldSources"),
    )
    """Optional per-field provenance (`ENV`, `YAML`, `DATABASE`, `DEFAULT`) for components supporting granular edits."""

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]
        serialize_by_alias = True


@dataclass
class ComponentListResponseVO(BaseResponse):
    """Response payload for `GET /api/extended/system/components`."""

    components: list[ComponentStatusVO] = field(default_factory=list)


@dataclass
class UpdateComponentConfigDTO(DataClassJSONMixin):
    """Request payload for `PUT /api/extended/system/components/{domain}`."""

    config: dict[str, Any] = field(default_factory=dict)
    """Updated configuration dictionary for the target component domain."""


@dataclass
class ComponentStatusResponseVO(BaseResponse):
    """Response payload for `PUT /api/extended/system/components/{domain}`."""

    component: ComponentStatusVO | None = None


@dataclass
class ServerFeaturesVO(BaseResponse):
    """Response payload for `GET /api/extended/system/features`."""

    running_components: list[str] = field(
        default_factory=list,
        metadata=field_options(alias="runningComponents"),
    )
    """Sorted domains of built-in components currently running on this server."""
