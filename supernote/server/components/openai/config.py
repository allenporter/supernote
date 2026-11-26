"""Configuration model for the OpenAI-compatible AI provider component (`OpenAIConfig`)."""

from __future__ import annotations

from dataclasses import dataclass, field

from mashumaro.config import TO_DICT_ADD_OMIT_NONE_FLAG, BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from supernote.server.config import ProviderConfig


@dataclass
class OpenAIConfig(DataClassJSONMixin):
    """Per-component settings for `supernote.server.components.openai`."""

    enabled: bool = False
    """Whether the OpenAI-compatible AI provider component is enabled."""

    api_key: str | None = None
    """Default API key for authenticating with the OpenAI-compatible server."""

    base_url: str | None = None
    """Default base URL for the OpenAI-compatible server (e.g. `http://localhost:11434/v1` for Ollama)."""

    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    """Named OpenAI-compatible provider entries (supports multiple servers such as `ollama` and `llamacpp`)."""

    def __post_init__(self) -> None:
        if (self.api_key or self.base_url) and "openai" not in self.providers:
            self.providers["openai"] = ProviderConfig(
                api_key=self.api_key,
                base_url=self.base_url,
                type="openai",
            )
        elif "openai" in self.providers:
            openai_entry = self.providers["openai"]
            if self.api_key is None:
                self.api_key = openai_entry.api_key
            if self.base_url is None:
                self.base_url = openai_entry.base_url

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]
