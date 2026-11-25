"""Administrative HTTP API routes (`/api/admin/*`) guarded by `require_admin`.

Serves core administrator endpoints consumed by the `supernote admin` CLI (`supernote.cli.admin`)
and Web UI admin dashboard:
- `GET /api/admin/users` and `POST /api/admin/users`: List and provision user accounts via `supernote.server.services.user.UserService`.
- `POST /api/admin/users/password`: Reset user passwords.
- `POST /api/admin/users/quota`: Update per-user storage quotas.
- `GET /api/admin/integrity`: Run VFS and blob consistency checks via `supernote.server.services.integrity.IntegrityService`.
"""

from aiohttp import web
from mashumaro.exceptions import InvalidFieldValue, MissingField

from supernote.models.base import (
    BaseResponse,
    create_error_response,
)
from supernote.models.user import UpdateUserQuotaDTO, UserRegisterDTO
from supernote.server.exceptions import SupernoteError
from supernote.server.keys import (
    INTEGRITY_SERVICE_KEY,
    USER_SERVICE_KEY,
)
from supernote.server.services.integrity import IntegrityService
from supernote.server.services.user import UserService

from .decorators import require_admin

routes = web.RouteTableDef()


@routes.post("/api/admin/users")
@require_admin
async def handle_create_user(request: web.Request) -> web.Response:
    """Create a new user (Admin only)."""
    req_data = await request.json()
    try:
        dto = UserRegisterDTO.from_dict(req_data)
    except (MissingField, ValueError):
        return web.json_response(
            create_error_response("Invalid request format").to_dict(),
            status=400,
        )

    user_service: UserService = request.app[USER_SERVICE_KEY]
    try:
        await user_service.create_user(dto)
        return web.json_response(BaseResponse().to_dict())
    except ValueError as e:
        return web.json_response(create_error_response(str(e)).to_dict(), status=400)


@routes.post("/api/admin/users/password")
@require_admin
async def handle_admin_update_password(request: web.Request) -> web.Response:
    """Update any user's password (Admin only)."""
    req_data = await request.json()
    # We reuse UpdatePasswordDTO but only look at the email and
    # new password fields.
    email = req_data.get("email")
    password_md5 = req_data.get("password")  # The md5 hash

    if not email or not password_md5:
        return web.json_response(
            create_error_response("Missing email or password").to_dict(), status=400
        )
    user_service: UserService = request.app[USER_SERVICE_KEY]
    try:
        await user_service.admin_reset_password(email, password_md5)
    except ValueError as e:
        return web.json_response(create_error_response(str(e)).to_dict(), status=400)
    except Exception as e:
        return SupernoteError.uncaught(e).to_response()

    return web.json_response(BaseResponse().to_dict())


@routes.post("/api/admin/users/quota")
@require_admin
async def handle_admin_update_quota(request: web.Request) -> web.Response:
    """Update a user's storage quota in bytes (Admin only)."""
    req_data = await request.json()
    try:
        dto = UpdateUserQuotaDTO.from_dict(req_data)
    except (MissingField, InvalidFieldValue, ValueError, TypeError):
        return web.json_response(
            create_error_response("Invalid request format").to_dict(),
            status=400,
        )

    if not dto.email:
        return web.json_response(
            create_error_response("Missing email").to_dict(), status=400
        )

    user_service: UserService = request.app[USER_SERVICE_KEY]
    try:
        await user_service.admin_set_user_quota(dto.email, dto.total_capacity)
    except ValueError as e:
        return web.json_response(create_error_response(str(e)).to_dict(), status=400)
    except Exception as e:
        return SupernoteError.uncaught(e).to_response()

    return web.json_response(BaseResponse().to_dict())


@routes.get("/api/admin/users")
@require_admin
async def handle_list_users(request: web.Request) -> web.Response:
    """List all users (Admin only)."""
    user_service: UserService = request.app[USER_SERVICE_KEY]
    user_vos = await user_service.list_user_profiles()
    return web.json_response([vo.to_dict() for vo in user_vos])


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
