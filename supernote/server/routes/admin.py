from collections.abc import Awaitable, Callable

from aiohttp import web
from mashumaro.exceptions import MissingField
from sqlalchemy import delete, select

from supernote.models.auth import UserVO
from supernote.models.base import (
    BaseResponse,
    ProcessingStatus,
    TaskType,
    create_error_response,
)
from supernote.models.extended import (
    HermesSummaryRetryVO,
    RecycleBinCleanupRunVO,
    SystemTaskVO,
)
from supernote.models.summary import UpdateSummaryDTO
from supernote.models.system import QueueStatusVO
from supernote.models.user import UserRegisterDTO
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import SystemTaskDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import LocalEventBus, NoteUpdatedEvent
from supernote.server.exceptions import SupernoteError
from supernote.server.services.summary import SummaryService
from supernote.server.services.user import UserService
from supernote.server.utils.paths import get_hermes_summary_id
from supernote.server.utils.tasks import get_task, update_task_status

routes = web.RouteTableDef()

# Matches HermesSummaryModule.task_type/get_task_key() in
# supernote/server/services/processor_modules/hermes_summary.py. Hermes
# summary generation is a file-level (not per-page) task, so its key is
# always "global".
HERMES_SUMMARY_TASK_TYPE = "HERMES_SUMMARY_GENERATION"
HERMES_SUMMARY_TASK_KEY = "global"


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
            user_id=u.id,
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
                UserFileDO.file_name.like("%.note")
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


@routes.post("/api/admin/recycle-bin/cleanup/run")
@require_admin
async def handle_recycle_bin_cleanup_run(request: web.Request) -> web.Response:
    """Manually run the recycle bin cleanup job now (Admin only).

    Purges recycle bin entries older than the configured retention window
    immediately, rather than waiting for the next scheduled run.
    """
    recycle_bin_cleanup_service = request.app["recycle_bin_cleanup_service"]
    purged_count = await recycle_bin_cleanup_service.run_once()
    return web.json_response(
        RecycleBinCleanupRunVO(purged_count=purged_count).to_dict()
    )


@routes.post("/api/admin/notes/{file_id}/hermes-summary/retry")
@require_admin
async def handle_hermes_summary_retry(request: web.Request) -> web.Response:
    """Manually rerun Hermes summary generation for one note (Admin only).

    Useful when OCR corrections or user feedback (e.g. a manual OCR fix)
    should trigger a fresh interpretation without waiting for the next
    `.note` sync to change the file's content hash on its own.
    """
    file_id_str = request.match_info.get("file_id")
    try:
        file_id = int(file_id_str) if file_id_str is not None else None
    except ValueError:
        file_id = None
    if file_id is None:
        return web.json_response(
            create_error_response("Invalid file_id").to_dict(), status=400
        )

    session_manager: DatabaseSessionManager = request.app["session_manager"]
    summary_service: SummaryService = request.app["summary_service"]
    processor_service = request.app["processor_service"]

    async with session_manager.session() as session:
        file_do = await session.get(UserFileDO, file_id)
        if not file_do:
            return web.json_response(
                create_error_response("File not found").to_dict(), status=404
            )
        user = await session.get(UserDO, file_do.user_id)
        user_email = user.email if user else None
        file_basis = file_do.storage_key or str(file_do.id)

    # HermesSummaryModule doesn't gate on this task's COMPLETED status the
    # way other modules do -- its `run_if_needed()` always re-checks, and
    # `process()` separately decides whether to actually call Hermes by
    # comparing a source hash against the one stored in the *existing Hermes
    # summary row's* `extra_metadata` (never in `f_system_task`; see
    # `HermesSummaryModule.process()`). So resetting the task row alone
    # would NOT force a fresh Hermes call when the underlying OCR text is
    # unchanged -- we also have to clear the stored hash on the summary
    # itself so the next run's hash comparison misses and regenerates.
    if user_email:
        hermes_uuid = get_hermes_summary_id(file_basis)
        existing_summary = await summary_service.get_summary_by_uuid(
            user_email, hermes_uuid
        )
        if existing_summary and existing_summary.id is not None:
            await summary_service.update_summary(
                user_email,
                UpdateSummaryDTO(id=existing_summary.id, metadata="{}"),
            )

    # Reset (or create) the task row to PENDING with no error, so the
    # response reflects a freshly-queued state rather than a stale
    # COMPLETED/FAILED one.
    await update_task_status(
        session_manager,
        file_id,
        HERMES_SUMMARY_TASK_TYPE,
        HERMES_SUMMARY_TASK_KEY,
        ProcessingStatus.PENDING,
    )

    await processor_service.enqueue_file(file_id)

    task = await get_task(
        session_manager, file_id, HERMES_SUMMARY_TASK_TYPE, HERMES_SUMMARY_TASK_KEY
    )
    task_vo = None
    if task:
        task_vo = SystemTaskVO(
            id=task.id,
            file_id=task.file_id,
            task_type=task.task_type,
            key=task.key,
            status=ProcessingStatus(task.status),
            retry_count=task.retry_count,
            last_error=task.last_error,
            update_time=task.update_time,
        )

    return web.json_response(
        HermesSummaryRetryVO(file_id=file_id, task=task_vo).to_dict()
    )
