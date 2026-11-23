"""Outbound webhooks server component."""

from __future__ import annotations

from supernote.server.core import ServerCore
from supernote.server.services.webhook import WebhookService

__all__ = ["WebhooksComponent"]


class WebhooksComponent:
    """Vertical component wrapping `WebhookService` lifecycle."""

    domain = "webhooks"
    dependencies: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._service: WebhookService | None = None

    async def async_setup(self, core: ServerCore) -> None:
        """Instantiate `WebhookService` from core configuration and services."""
        self._service = WebhookService(
            core.config.webhooks,
            core.event_bus,
            core.user_service,
        )

    async def async_start(self, core: ServerCore) -> None:
        """Start outbound webhook event subscriptions and HTTP client session."""
        if self._service is not None:
            await self._service.start()

    async def async_stop(self, core: ServerCore) -> None:
        """Idempotently drain in-flight webhook deliveries and close the HTTP session."""
        service = self._service
        self._service = None
        if service is not None:
            await service.stop()
