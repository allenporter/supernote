from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.config import TO_DICT_ADD_OMIT_NONE_FLAG, BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin


@dataclass
class BaseResponse(DataClassJSONMixin):
    """Base response class."""

    success: bool = True
    error_code: str | None = field(
        metadata=field_options(alias="errorCode"), default=None
    )
    error_msg: str | None = field(
        metadata=field_options(alias="errorMsg"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


def create_error_response(
    error_msg: str, error_code: str | None = None
) -> BaseResponse:
    """Create an error response."""
    return BaseResponse(success=False, error_code=error_code, error_msg=error_msg)
