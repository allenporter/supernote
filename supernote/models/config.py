"""Wire models for the server component configuration API."""

from __future__ import annotations

from dataclasses import dataclass, field

from mashumaro import field_options

from .base import BaseResponse

__all__ = ["ServerFeaturesVO"]


@dataclass
class ServerFeaturesVO(BaseResponse):
    """Response payload for `GET /api/extended/system/features`."""

    running_components: list[str] = field(
        default_factory=list,
        metadata=field_options(alias="runningComponents"),
    )
    """Sorted domains of built-in components currently running on this server."""
