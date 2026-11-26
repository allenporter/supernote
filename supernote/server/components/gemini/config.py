"""Configuration model for the Google Gemini AI provider component (`GeminiConfig`)."""

from __future__ import annotations

from dataclasses import dataclass, field

from mashumaro.config import TO_DICT_ADD_OMIT_NONE_FLAG, BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from supernote.server.config import ProviderConfig


@dataclass
class GeminiConfig(DataClassJSONMixin):
    """Per-component settings for `supernote.server.components.gemini`."""

    enabled: bool = False
    """Whether the Google Gemini AI provider component is enabled."""

    api_key: str | None = None
    """Default Google Gemini API key for authenticating requests."""

    base_url: str | None = None
    """Optional custom Gemini API base URL."""

    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    """Named Gemini provider entries (populated automatically from `api_key`/`base_url` when `gemini` is not explicitly in `providers`)."""

    def __post_init__(self) -> None:
        if (self.api_key or self.base_url) and "gemini" not in self.providers:
            self.providers["gemini"] = ProviderConfig(
                api_key=self.api_key,
                base_url=self.base_url,
                type="gemini",
            )
        elif "gemini" in self.providers:
            gemini_entry = self.providers["gemini"]
            if self.api_key is None:
                self.api_key = gemini_entry.api_key
            if self.base_url is None:
                self.base_url = gemini_entry.base_url

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]
