"""Storage integrity verification component (`IntegrityComponent`).

Audits consistency between SQLite metadata tables and physical blobs stored in
`USER_DATA_BUCKET` and `CACHE_BUCKET`, detecting missing or orphaned blobs,
size and MD5 mismatches, broken VFS parent chains, and failed or incomplete
processing artifacts. Administrators invoke these checks on demand via
`GET /api/admin/integrity` (`supernote admin integrity`) for a single user, a
single file, or across the full disk.

Provides `IntegrityComponent`, `IntegrityService`, and `INTEGRITY_SERVICE_KEY`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aiohttp import web

from supernote.server.core import ServerCore

from .service import IntegrityService

__all__ = [
    "INTEGRITY_SERVICE_KEY",
    "IntegrityComponent",
    "IntegrityService",
]

INTEGRITY_SERVICE_KEY: web.AppKey[IntegrityService] = web.AppKey("integrity_service")


class IntegrityComponent:
    """Vertical component managing two-way storage integrity verification."""

    domain = "integrity"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("http",)

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Instantiate `IntegrityService` and expose it via `INTEGRITY_SERVICE_KEY`."""
        core.app[INTEGRITY_SERVICE_KEY] = IntegrityService(
            core.session_manager,
            core.blob_storage,
        )

    async def async_start(self, core: ServerCore) -> None:
        """No-op; integrity audits run on demand when requested by administrators."""

    async def async_stop(self, core: ServerCore) -> None:
        """No-op; integrity service holds no background tasks."""
