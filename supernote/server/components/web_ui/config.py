"""Configuration model for the Web UI static SPA server component (`WebUiConfig`)."""

from __future__ import annotations

from dataclasses import dataclass

from mashumaro.mixins.json import DataClassJSONMixin

__all__ = ["WebUiConfig"]


@dataclass
class WebUiConfig(DataClassJSONMixin):
    """Per-component settings for `supernote.server.components.web_ui`."""

    enabled: bool = True
    """Whether the single-page Web UI dashboard and `/static/` assets are served."""

    notebook_preview: bool = True
    """Whether notebook page PNG previews are rendered and served for Web UI viewing."""
