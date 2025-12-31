"""Module for API base classes."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Self

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin


@dataclass
class BaseResponse(DataClassJSONMixin):
    """Base response class."""

    success: bool = True
    """Whether the request was successful."""

    error_code: str | None = field(
        metadata=field_options(alias="errorCode"), default=None
    )
    """Error code."""

    error_msg: str | None = field(
        metadata=field_options(alias="errorMsg"), default=None
    )
    """Error message."""

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True


def create_error_response(
    error_msg: str, error_code: str | None = None
) -> BaseResponse:
    """Create an error response."""
    return BaseResponse(success=False, error_code=error_code, error_msg=error_msg)


class BaseEnum(Enum):
    """Base enum class."""

    @classmethod
    def from_value(cls, value: int) -> Self:
        for member in cls:
            if member.value == value:
                return member
        raise ValueError(f"Invalid {cls.__name__} value: {value}")


class BooleanEnum(str, BaseEnum):
    """Boolean enum."""

    YES = "Y"
    NO = "N"


@dataclass
class CommonList(BaseResponse):
    """Common list response class."""

    total: int = 0
    """Total count of items."""

    pages: int = 0
    """Total pages."""

    size: int = field(metadata=field_options(alias="size"), default=20)
    """Current page size."""

    vo_list: list[Any] = field(
        metadata=field_options(alias="voList"), default_factory=list
    )
    """List of items."""

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
