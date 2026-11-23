"""Configuration schema for the outbound webhooks server component."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from mashumaro.config import TO_DICT_ADD_OMIT_NONE_FLAG, BaseConfig
from mashumaro.mixins.yaml import DataClassYAMLMixin

__all__ = ["WebhookConfig", "WebhookEndpointConfig"]


@dataclass
class WebhookEndpointConfig(DataClassYAMLMixin):
    """A single outbound webhook subscriber."""

    url: str = ""
    """The HTTP(S) endpoint that receives the webhook POST request."""

    user: str = ""
    """Email address of the user account whose events this endpoint receives."""

    secret: str = ""
    """Shared secret used to HMAC-SHA256 sign the payload.

    Never logged. Sent to receivers via the `X-Supernote-Signature` header so
    they can verify the payload was not tampered with in transit.
    """

    events: list[str] = field(default_factory=list)
    """Event names this endpoint wants to receive, e.g. `note.sync_completed`.

    If empty (the default), the endpoint receives every event for `user`.
    """

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError(
                f"Webhook endpoint URL must use http or https scheme with a valid host: {self.url!r}"
            )
        if not self.user or not self.user.strip():
            raise ValueError(
                "Webhook endpoint must specify a non-empty user email address."
            )

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class WebhookConfig(DataClassYAMLMixin):
    """Outbound webhook dispatch configuration."""

    enabled: bool = False
    """Whether outbound webhook dispatch is enabled.

    Env Var: `SUPERNOTE_WEBHOOKS_ENABLED`
    """

    endpoints: list[WebhookEndpointConfig] = field(default_factory=list)
    """Configured webhook subscribers."""

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]
