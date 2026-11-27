"""Configuration model for the HTTP transport platform component (`HttpConfig`)."""

from __future__ import annotations

from dataclasses import dataclass, field

from mashumaro.mixins.json import DataClassJSONMixin

_DEFAULT_TRUSTED_PROXIES: tuple[str, ...] = ("127.0.0.1", "::1", "172.17.0.0/16")
_ALLOWED_PROXY_MODES: frozenset[str] = frozenset({"disabled", "relaxed", "strict"})


@dataclass
class HttpConfig(DataClassJSONMixin):
    """Per-component settings for `supernote.server.components.http`."""

    enabled: bool = True
    """Whether the HTTP transport platform is enabled."""

    proxy_mode: str | None = None
    """Proxy header handling mode: `None`/`'disabled'` (ignore proxy headers), `'relaxed'` (trust immediate upstream), or `'strict'` (require specific trusted IPs)."""

    trusted_proxies: list[str] = field(
        default_factory=lambda: list(_DEFAULT_TRUSTED_PROXIES)
    )
    """Trusted proxy IPs or CIDR networks used when `proxy_mode == 'strict'`."""

    def __post_init__(self) -> None:
        if self.proxy_mode is not None:
            normalized = self.proxy_mode.strip().lower()
            if normalized not in _ALLOWED_PROXY_MODES:
                raise ValueError(
                    f"http.proxy_mode must be one of {sorted(_ALLOWED_PROXY_MODES)} or None"
                )
            self.proxy_mode = None if normalized == "disabled" else normalized
