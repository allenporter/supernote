"""HTTP platform route for administrator storage integrity audits.

Exposes `GET /api/admin/integrity` (`@require_admin`), consumed by the
`supernote admin integrity` CLI (`supernote.client.admin.AdminClient`) to run
on-demand two-way consistency audits between SQLite VFS/processing metadata and
physical blobs in `USER_DATA_BUCKET` and `CACHE_BUCKET`. Supports scoping to a
single user (`?email=...`), a single file (`?email=...&file_id=...`), or an
all-user disk sweep (`?full_disk=true`), returning an `IntegrityReportVO` with
detected anomalies and remediation hints.
"""

from __future__ import annotations

from aiohttp import web

from supernote.models.base import create_error_response
from supernote.server.components.http import HttpRegistrar
from supernote.server.core import ServerCore
from supernote.server.keys import USER_SERVICE_KEY
from supernote.server.routes.decorators import require_admin
from supernote.server.services.user import UserService

from . import INTEGRITY_SERVICE_KEY
from .service import IntegrityService

__all__ = [
    "async_setup_http",
]

routes = web.RouteTableDef()


@routes.get("/api/admin/integrity")
@require_admin
async def handle_verify_integrity(request: web.Request) -> web.Response:
    """Verify VFS and blob storage integrity for a user or full disk (Admin only)."""
    email = request.query.get("email")
    file_id_str = request.query.get("file_id")
    full_disk_str = request.query.get("full_disk")

    if full_disk_str is not None and full_disk_str not in ("true", "false"):
        return web.json_response(
            create_error_response(f"Invalid full_disk: {full_disk_str}").to_dict(),
            status=400,
        )
    full_disk = full_disk_str == "true"

    integrity_service: IntegrityService = request.app[INTEGRITY_SERVICE_KEY]

    if full_disk:
        if email or file_id_str is not None:
            return web.json_response(
                create_error_response(
                    "Cannot combine full_disk with email or file_id"
                ).to_dict(),
                status=400,
            )
        report = await integrity_service.verify_full_disk()
        return web.json_response(report.to_dict())

    if not email:
        return web.json_response(
            create_error_response("Missing required parameter: email").to_dict(),
            status=400,
        )

    try:
        file_id = int(file_id_str) if file_id_str is not None else None
    except ValueError:
        return web.json_response(
            create_error_response("Invalid file_id").to_dict(),
            status=400,
        )

    user_service: UserService = request.app[USER_SERVICE_KEY]
    user = await user_service.get_user_by_email(email)
    if user is None:
        return web.json_response(
            create_error_response(f"User not found: {email}").to_dict(),
            status=404,
        )

    report = await integrity_service.verify_user_storage(
        user_id=user.id, file_id=file_id
    )
    return web.json_response(report.to_dict())


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register integrity HTTP routes on ``registrar.router``."""
    registrar.router.add_routes(routes)
