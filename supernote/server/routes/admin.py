from collections.abc import Awaitable, Callable

from aiohttp import web
from mashumaro.exceptions import MissingField

from supernote.models.auth import UserVO
from supernote.models.base import BaseResponse, create_error_response
from supernote.models.user import UserRegisterDTO
from supernote.server.exceptions import SupernoteError
from supernote.server.services.user import UserService

routes = web.RouteTableDef()


def require_admin(
    handler: Callable[[web.Request], Awaitable[web.Response]],
) -> Callable[[web.Request], Awaitable[web.Response]]:
    """Decorator to require admin privileges."""

    async def wrapper(request: web.Request) -> web.Response:
        user_service: UserService = request.app["user_service"]
        username = request.get("user")
        if not username:
            return web.json_response(
                create_error_response("Unauthorized").to_dict(), status=401
            )

        user = await user_service._get_user_do(str(username))
        if not user or not user.is_admin:
            return web.json_response(
                create_error_response("Forbidden: Admin access required").to_dict(),
                status=403,
            )

        return await handler(request)

    return wrapper


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

    user_service: UserService = request.app["user_service"]
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
    user_service: UserService = request.app["user_service"]
    try:
        await user_service.admin_reset_password(email, password_md5)
    except ValueError as e:
        return web.json_response(create_error_response(str(e)).to_dict(), status=400)
    except Exception as e:
        return SupernoteError.uncaught(e).to_response()

    return web.json_response(BaseResponse().to_dict())


@routes.get("/api/admin/users")
@require_admin
async def handle_list_users(request: web.Request) -> web.Response:
    """List all users (Admin only)."""
    user_service: UserService = request.app["user_service"]
    users = await user_service.list_users()

    user_vos = [
        UserVO(
            user_name=u.display_name or u.email,
            email=u.email,
            phone=u.phone or "",
            country_code="1",
            total_capacity=u.total_capacity,
            file_server="",
            avatars_url=u.avatar or "",
            birthday="",
            sex="",
        )
        for u in users
    ]

    # Simple list response for now
    return web.json_response([vo.to_dict() for vo in user_vos])


@routes.post("/api/admin/queue/stop")
@require_admin
async def handle_stop_queue(request: web.Request) -> web.Response:
    """Stop/pause the queue processing."""
    processor_service = request.app["processor_service"]
    await processor_service.pause()
    return web.json_response(BaseResponse().to_dict())


@routes.post("/api/admin/queue/start")
@require_admin
async def handle_start_queue(request: web.Request) -> web.Response:
    """Start/resume the queue processing."""
    processor_service = request.app["processor_service"]
    await processor_service.resume()
    return web.json_response(BaseResponse().to_dict())


@routes.get("/api/admin/queue/status")
@require_admin
async def handle_queue_status(request: web.Request) -> web.Response:
    """Get the queue status."""
    processor_service = request.app["processor_service"]
    from supernote.models.system import QueueStatusVO

    status = QueueStatusVO(
        paused=not processor_service.is_processing_enabled(),
        queue_size=processor_service.queue.qsize(),
        processing_files=list(processor_service.processing_files),
    )
    return web.json_response(status.to_dict())
