"""Configuration model for the `.note` to PNG and PDF conversion component (`ConversionConfig`)."""

from __future__ import annotations

from dataclasses import dataclass

from mashumaro.mixins.json import DataClassJSONMixin


@dataclass
class ConversionConfig(DataClassJSONMixin):
    """Per-component settings for `supernote.server.components.conversion`."""

    enabled: bool = True
    """Whether the `.note` conversion component is enabled."""

    notebook_preview: bool = True
    """Whether to generate and serve notebook page PNG previews in the Web UI and on-demand endpoints."""
