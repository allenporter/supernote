"""Administrative HTTP API routes (`/api/admin/*`) guarded by `require_admin`.

Serves core administrator endpoints consumed by the `supernote admin` CLI (`supernote.cli.admin`)
and Web UI admin dashboard:
- `GET /api/admin/users` and `POST /api/admin/users`: List and provision user accounts via `supernote.server.services.user.UserService`.
- `POST /api/admin/users/password`: Reset user passwords.
- `POST /api/admin/users/quota`: Update per-user storage quotas.
"""

from aiohttp import web

from supernote.models.base import (
    BaseResponse,
    create_error_response,
)
from supernote.models.user import UpdateUserQuotaDTO, UserRegisterDTO
from supernote.server.exceptions import InvalidInputError, SupernoteError
from supernote.server.keys import USER_SERVICE_KEY
from supernote.server.services.user import UserService
from supernote.server.utils.request import parse_json_dto, parse_json_object

from .decorators import require_admin

routes = web.RouteTableDef()


@routes.post("/api/admin/users")
@require_admin
async def handle_create_user(request: web.Request) -> web.Response:
    """Create a new user (Admin only)."""
    try:
        dto = await parse_json_dto(request, UserRegisterDTO)
    except InvalidInputError:
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
    try:
        req_data = await parse_json_object(request)
    except InvalidInputError as err:
        return err.to_response()
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
    try:
        dto = await parse_json_dto(request, UpdateUserQuotaDTO)
    except InvalidInputError:
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
