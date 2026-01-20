"""Module for server-specific extension models.

These are for APIs that are not part of the standard API offering, specific
to our new server.
"""

from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from supernote.models.base import BaseResponse
from supernote.models.summary import SummaryItem


@dataclass
class WebSummaryListRequestDTO(DataClassJSONMixin):
    """Request DTO for listing summaries by file ID (Web Extension)."""

    file_id: int = field(metadata=field_options(alias="fileId"))
    """The ID of the file to list summaries for."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebSummaryListVO(BaseResponse):
    """Response VO for listing summaries (Web Extension)."""

    summary_do_list: list[SummaryItem] = field(
        metadata=field_options(alias="summaryDOList"), default_factory=list
    )
    """List of summary items."""

    total_records: int = field(metadata=field_options(alias="totalRecords"), default=0)
    """Total number of records."""

    class Config(BaseConfig):
        serialize_by_alias = True
