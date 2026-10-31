"""Administrative HTTP API routes (`/api/admin/*`) guarded by `require_admin`.

Serves administrator endpoints consumed by the `supernote admin` CLI (`supernote.cli.admin`)
and Web UI admin dashboard:
- `GET /api/admin/users` and `POST /api/admin/users`: List and provision user accounts via `supernote.server.services.user.UserService`.
- `POST /api/admin/users/reset-password`: Reset user passwords.
- `GET /api/admin/queue/status`, `POST /api/admin/queue/stop`, `POST /api/admin/queue/start`: Inspect, pause, and resume `supernote.server.services.processor.ProcessorService`.
- `POST /api/admin/notes/reprocess`: Clear `SystemTaskDO` checkpoints and re-enqueue `.note` files.
- `GET /api/admin/tasks`: Query recent or failed background processing tasks.
- `POST /api/admin/integrity`: Run VFS and blob consistency checks via `supernote.server.services.integrity.IntegrityService`.
"""

from collections.abc import Awaitable, Callable

from aiohttp import web
from mashumaro.exceptions import MissingField
from sqlalchemy import delete, select

from supernote.models.base import (
    BaseResponse,
    ProcessingStatus,
    TaskType,
    create_error_response,
)
from supernote.models.extended import SystemTaskListVO, SystemTaskVO
from supernote.models.system import QueueStatusVO
from supernote.models.user import UserRegisterDTO
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus, NoteUpdatedEvent
from supernote.server.exceptions import SupernoteError
from supernote.server.services.integrity import IntegrityService
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

        user = await user_service.get_user_by_email(str(username))
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
    user_vos = await user_service.list_user_profiles()
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

    status = QueueStatusVO(
        paused=not processor_service.is_processing_enabled(),
        queue_size=processor_service.queue.qsize(),
        processing_files=list(processor_service.processing_files),
    )
    return web.json_response(status.to_dict())


@routes.post("/api/admin/reprocess")
@require_admin
async def handle_reprocess(request: web.Request) -> web.Response:
    """Clear and trigger reprocessing of note tasks (Admin only)."""
    req_data = await request.json()
    task_type = req_data.get("task_type", "summary")
    file_id = req_data.get("file_id")

    session_manager: DatabaseSessionManager = request.app["session_manager"]
    event_bus: LocalEventBus = request.app["event_bus"]

    async with session_manager.session() as session:
        stmt = delete(SystemTaskDO)

        if task_type.upper() != "ALL":
            try:
                mapped_type = TaskType.from_friendly(task_type)
            except ValueError:
                return web.json_response(
                    create_error_response(f"Invalid task_type: {task_type}").to_dict(),
                    status=400,
                )
            stmt = stmt.where(SystemTaskDO.task_type == mapped_type.value)

        # Get target file IDs to trigger events
        if file_id is not None:
            file_stmt = select(UserFileDO.user_id).where(UserFileDO.id == file_id)
            file_result = await session.execute(file_stmt)
            uid = file_result.scalar_one_or_none()
            targets = [(file_id, uid if uid is not None else 0)]
            stmt = stmt.where(SystemTaskDO.file_id == file_id)
        else:
            file_stmt = select(UserFileDO.id, UserFileDO.user_id).where(
                UserFileDO.file_name.like("%.note"),
                UserFileDO.is_active == "Y",
            )
            file_result = await session.execute(file_stmt)
            targets = list(file_result.all())

        await session.execute(stmt)
        await session.commit()

    # Publish NoteUpdatedEvent to trigger immediate reprocessing
    for fid, uid in targets:
        await event_bus.publish(
            NoteUpdatedEvent(file_id=fid, user_id=uid, file_path="")
        )

    return web.json_response(BaseResponse().to_dict())


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

    integrity_service: IntegrityService = request.app["integrity_service"]

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

    user_service: UserService = request.app["user_service"]
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


@routes.get("/api/admin/tasks")
@require_admin
async def handle_admin_list_tasks(request: web.Request) -> web.Response:
    """List system processing tasks with optional filters (Admin only)."""
    status_param = request.query.get("status")
    file_id_str = request.query.get("file_id")
    task_type_param = request.query.get("task_type")
    limit_str = request.query.get("limit")

    try:
        file_id = int(file_id_str) if file_id_str is not None else None
        limit = int(limit_str) if limit_str is not None else 100
    except ValueError:
        return web.json_response(
            create_error_response("Invalid file_id or limit").to_dict(),
            status=400,
        )

    status_filter: str | None = None
    if status_param:
        try:
            status_filter = ProcessingStatus(status_param.upper()).value
        except ValueError:
            return web.json_response(
                create_error_response(f"Invalid status: {status_param}").to_dict(),
                status=400,
            )

    task_type_filter: str | None = None
    if task_type_param:
        try:
            task_type_filter = TaskType.from_friendly(task_type_param).value
        except ValueError:
            return web.json_response(
                create_error_response(
                    f"Invalid task_type: {task_type_param}"
                ).to_dict(),
                status=400,
            )

    processor_service = request.app["processor_service"]
    tasks = await processor_service.list_system_tasks(
        limit=limit,
        status=status_filter,
        file_id=file_id,
        task_type=task_type_filter,
    )
    task_vos = [
        SystemTaskVO(
            id=t.id,
            file_id=t.file_id,
            task_type=t.task_type,
            key=t.key,
            status=ProcessingStatus(t.status),
            retry_count=t.retry_count,
            last_error=t.last_error,
            update_time=t.update_time,
        )
        for t in tasks
    ]
    return web.json_response(SystemTaskListVO(tasks=task_vos).to_dict())
