from aiohttp import web
from mashumaro.exceptions import MissingField

from supernote.models.auth import (
    LoginDTO,
    QueryTokenVO,
    RandomCodeDTO,
    RandomCodeVO,
    UserCheckDTO,
    UserQueryByIdVO,
)
from supernote.models.base import BaseResponse, create_error_response
from supernote.models.equipment import BindEquipmentDTO, UnbindEquipmentDTO
from supernote.models.user import (
    LoginRecordDTO,
    RetrievePasswordDTO,
    UpdateEmailDTO,
    UpdatePasswordDTO,
    UserRegisterDTO,
)
from supernote.server.exceptions import SupernoteError
from supernote.server.services.user import UserService
from supernote.server.utils.rate_limit import (
    LIMIT_LOGIN_ACCOUNT_MAX,
    LIMIT_LOGIN_ACCOUNT_WINDOW,
    LIMIT_LOGIN_IP_MAX,
    LIMIT_LOGIN_IP_WINDOW,
    LIMIT_PW_RESET_MAX,
    LIMIT_PW_RESET_WINDOW,
    LOGIN_KEY_ACCOUNT,
    LOGIN_KEY_IP,
    RESET_KEY_ACCOUNT,
    RESET_KEY_IP,
    RateLimitExceeded,
)

from .decorators import public_route

routes = web.RouteTableDef()


@routes.post("/api/terminal/equipment/unlink")
@public_route
async def handle_equipment_unlink(request: web.Request) -> web.Response:
    # Endpoint: POST /api/terminal/equipment/unlink
    # Purpose: Device requests to unlink itself from the account/server.
    req_data = await request.json()
    try:
        unlink_req = UnbindEquipmentDTO.from_dict(req_data)
    except (MissingField, ValueError):
        return web.json_response(
            create_error_response("Invalid request format").to_dict(),
            status=400,
        )

    user_service: UserService = request.app["user_service"]
    await user_service.unlink_equipment(unlink_req.equipment_no)
    return web.json_response(BaseResponse().to_dict())


@routes.post("/api/official/user/check/exists/server")
@public_route
async def handle_check_user_exists(request: web.Request) -> web.Response:
    # Endpoint: POST /api/official/user/check/exists/server
    # Purpose: Check if the user exists on this server.
    req_data = await request.json()
    user_check_req = UserCheckDTO.from_dict(req_data)
    user_service: UserService = request.app["user_service"]
    if await user_service.check_user_exists(user_check_req.email or ""):
        return web.json_response(BaseResponse().to_dict())
    else:
        return web.json_response(create_error_response("User not found").to_dict())


@routes.post("/api/user/query/token")
@routes.get("/api/user/query/token")
@public_route
async def handle_query_token(request: web.Request) -> web.Response:
    # Endpoint: POST /api/user/query/token
    # Purpose: Initial token check (often empty request)
    return web.json_response(QueryTokenVO().to_dict(omit_none=False))


@routes.post("/api/official/user/query/random/code")
@public_route
async def handle_random_code(request: web.Request) -> web.Response:
    # Endpoint: POST /api/official/user/query/random/code
    # Purpose: Get challenge for password hashing
    req_data = await request.json()
    code_req = RandomCodeDTO.from_dict(req_data)
    user_service: UserService = request.app["user_service"]
    random_code, timestamp = await user_service.generate_random_code(code_req.account)
    return web.json_response(
        RandomCodeVO(random_code=random_code, timestamp=timestamp).to_dict()
    )


@routes.post("/api/official/user/account/login/new")
@routes.post("/api/official/user/account/login/equipment")
@public_route
async def handle_login(request: web.Request) -> web.Response:
    # Endpoint: POST /api/official/user/account/login/new
    # Purpose: Login with hashed password
    user_service: UserService = request.app["user_service"]
    req_data = await request.json()
    login_req = LoginDTO.from_dict(req_data)

    # Extract IP if possible
    ip = request.remote or "unknown"

    # RATE LIMIT CHECKS
    rate_limiter = request.app["rate_limiter"]
    try:
        await rate_limiter.check(
            f"{LOGIN_KEY_IP}:{ip}",
            limit=LIMIT_LOGIN_IP_MAX,
            window=LIMIT_LOGIN_IP_WINDOW,
        )
        await rate_limiter.check(
            f"{LOGIN_KEY_ACCOUNT}:{login_req.account}",
            limit=LIMIT_LOGIN_ACCOUNT_MAX,
            window=LIMIT_LOGIN_ACCOUNT_WINDOW,
        )
    except RateLimitExceeded as e:
        return e.to_response()

    result = await user_service.login(
        account=login_req.account,
        password_hash=login_req.password,
        timestamp=login_req.timestamp or "",
        equipment_no=login_req.equipment_no,
        equipment=login_req.equipment,
        ip=ip,
    )
    if not result:
        return web.json_response(
            create_error_response("Invalid credentials").to_dict(),
            status=401,
        )

    return web.json_response(result.to_dict())


@routes.post("/api/terminal/user/bindEquipment")
@public_route
async def handle_bind_equipment(request: web.Request) -> web.Response:
    # Endpoint: POST /api/terminal/user/bindEquipment
    # Purpose: Bind the device to the account.
    req_data = await request.json()
    try:
        bind_req = BindEquipmentDTO.from_dict(req_data)
    except (MissingField, ValueError):
        return web.json_response(
            create_error_response("Missing data").to_dict(), status=400
        )

    user_service: UserService = request.app["user_service"]
    await user_service.bind_equipment(bind_req.account, bind_req.equipment_no)
    return web.json_response(BaseResponse().to_dict())


@routes.post("/api/user/query")
async def handle_user_query(request: web.Request) -> web.Response:
    # Endpoint: POST /api/user/query
    # Purpose: Get user details.
    user_service: UserService = request.app["user_service"]
    account = request.get("user")
    if not account:
        return web.json_response(
            create_error_response("Unauthorized").to_dict(), status=401
        )
    user_vo = await user_service.get_user_profile(str(account))
    if not user_vo:
        return web.json_response(
            create_error_response("User not found").to_dict(),
            status=404,
        )

    return web.json_response(
        UserQueryByIdVO(
            user=user_vo,
            is_user=True,
            equipment_no=request.get("equipment_no"),
        ).to_dict()
    )


@routes.post("/api/user/register")
@public_route
async def handle_register(request: web.Request) -> web.Response:
    """Register a new user."""
    # Endpoint: POST /api/user/register

    req_data = await request.json()
    try:
        dto = UserRegisterDTO.from_dict(req_data)
    except (MissingField, ValueError) as e:
        return web.json_response(create_error_response(str(e)).to_dict(), status=400)

    user_service: UserService = request.app["user_service"]
    try:
        await user_service.register(dto)
        return web.json_response(BaseResponse().to_dict())
    except ValueError as e:
        return web.json_response(create_error_response(str(e)).to_dict(), status=400)
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/user/unregister")
async def handle_unregister(request: web.Request) -> web.Response:
    """Unregister a user."""
    # Requires auth
    account = request.get("user")
    if not account:
        return web.json_response(
            create_error_response("Unauthorized").to_dict(), status=401
        )

    user_service: UserService = request.app["user_service"]
    await user_service.unregister(str(account))
    return web.json_response(BaseResponse().to_dict())


@routes.put("/api/user/password")
async def handle_update_password(request: web.Request) -> web.Response:
    """Update user password."""
    account = request.get("user")
    if not account:
        return web.json_response(
            create_error_response("Unauthorized").to_dict(), status=401
        )

    req_data = await request.json()
    dto = UpdatePasswordDTO.from_dict(req_data)
    user_service: UserService = request.app["user_service"]
    await user_service.update_password(str(account), dto)
    return web.json_response(BaseResponse().to_dict())


@routes.put("/api/user/email")
async def handle_update_email(request: web.Request) -> web.Response:
    """Update user email."""
    account = request.get("user")
    if not account:
        return web.json_response(
            create_error_response("Unauthorized").to_dict(), status=401
        )

    req_data = await request.json()
    dto = UpdateEmailDTO.from_dict(req_data)
    user_service: UserService = request.app["user_service"]
    await user_service.update_email(str(account), dto)
    return web.json_response(BaseResponse().to_dict())


@routes.post("/api/official/user/retrieve/password")
@public_route
async def handle_retrieve_password(request: web.Request) -> web.Response:
    """Retrieve password."""
    if not request.app["config"].auth.enable_remote_password_reset:
        return web.json_response(
            create_error_response("Remote password reset is disabled").to_dict(),
            status=403,
        )

    req_data = await request.json()
    req_data = await request.json()
    dto = RetrievePasswordDTO.from_dict(req_data)
    user_service: UserService = request.app["user_service"]

    # Extract target account and password from DTO
    account = dto.email or dto.telephone or ""

    # RATE LIMIT CHECK
    # Strict Limit: 5 attempts / hour
    # We use a longer window for password reset to prevent enumeration
    ip = request.remote or "unknown"
    rate_limiter = request.app["rate_limiter"]
    try:
        await rate_limiter.check(
            f"{RESET_KEY_IP}:{ip}",
            limit=LIMIT_PW_RESET_MAX,
            window=LIMIT_PW_RESET_WINDOW,
        )
        await rate_limiter.check(
            f"{RESET_KEY_ACCOUNT}:{account}",
            limit=LIMIT_PW_RESET_MAX,
            window=LIMIT_PW_RESET_WINDOW,
        )
    except RateLimitExceeded as e:
        return e.to_response()

    if await user_service.retrieve_password(account, dto.password):
        return web.json_response(BaseResponse().to_dict())
    else:
        return web.json_response(
            create_error_response("User not found").to_dict(), status=404
        )


# TODO: Actually implement the return values for this.
# TODO: Also implement sensitive query operations and record them for all operations
# done on the user (update, edit settings, reset passwd, etc)
@routes.post("/api/user/query/loginRecord")
async def handle_login_record(request: web.Request) -> web.Response:
    """Query login records."""
    account = request.get("user")
    if not account:
        return web.json_response(
            create_error_response("Unauthorized").to_dict(), status=401
        )

    req_data = await request.json()
    dto = LoginRecordDTO.from_dict(req_data)
    user_service: UserService = request.app["user_service"]

    page_no = int(dto.page_no or 1)
    page_size = int(dto.page_size or 20)

    records, total = await user_service.query_login_records(
        str(account), page_no, page_size
    )

    records, total = await user_service.query_login_records(
        str(account), page_no, page_size
    )

    return web.json_response(
        {
            "data": [r.to_dict() for r in records],
            "total": total,
            # ... other standard response fields
        }
    )
