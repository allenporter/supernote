from aiohttp import web
from mashumaro.exceptions import MissingField

from supernote.server.models.auth import (
    BindEquipmentRequest,
    LoginRequest,
    LoginResponse,
    RandomCodeRequest,
    RandomCodeResponse,
    UnlinkRequest,
    UserCheckRequest,
    UserQueryResponse,
)
from supernote.server.models.base import BaseResponse, create_error_response
from supernote.server.services.user import UserService

from .decorators import public_route

routes = web.RouteTableDef()


@routes.post("/api/terminal/equipment/unlink")
@public_route
async def handle_equipment_unlink(request: web.Request) -> web.Response:
    # Endpoint: POST /api/terminal/equipment/unlink
    # Purpose: Device requests to unlink itself from the account/server.
    req_data = await request.json()
    try:
        unlink_req = UnlinkRequest.from_dict(req_data)
    except (MissingField, ValueError):
        return web.json_response(
            create_error_response("Invalid request format").to_dict(),
            status=400,
        )

    user_service: UserService = request.app["user_service"]
    user_service.unlink_equipment(unlink_req.equipment_no)
    return web.json_response(BaseResponse().to_dict())


@routes.post("/api/official/user/check/exists/server")
@public_route
async def handle_check_user_exists(request: web.Request) -> web.Response:
    # Endpoint: POST /api/official/user/check/exists/server
    # Purpose: Check if the user exists on this server.
    req_data = await request.json()
    user_check_req = UserCheckRequest.from_dict(req_data)
    user_service: UserService = request.app["user_service"]
    if user_service.check_user_exists(user_check_req.email):
        return web.json_response(BaseResponse().to_dict())
    else:
        return web.json_response(create_error_response("User not found").to_dict())


@routes.post("/api/user/query/token")
@public_route
async def handle_query_token(request: web.Request) -> web.Response:
    # Endpoint: POST /api/user/query/token
    # Purpose: Initial token check (often empty request)
    return web.json_response(BaseResponse().to_dict())


@routes.post("/api/official/user/query/random/code")
@public_route
async def handle_random_code(request: web.Request) -> web.Response:
    # Endpoint: POST /api/official/user/query/random/code
    # Purpose: Get challenge for password hashing
    req_data = await request.json()
    code_req = RandomCodeRequest.from_dict(req_data)
    user_service: UserService = request.app["user_service"]
    random_code, timestamp = user_service.generate_random_code(code_req.account)
    return web.json_response(
        RandomCodeResponse(random_code=random_code, timestamp=timestamp).to_dict()
    )


@routes.post("/api/official/user/account/login/new")
@routes.post("/api/official/user/account/login/equipment")
@public_route
async def handle_login(request: web.Request) -> web.Response:
    # Endpoint: POST /api/official/user/account/login/new
    # Purpose: Login with hashed password
    user_service: UserService = request.app["user_service"]

    req_data = await request.json()

    login_req = LoginRequest.from_dict(req_data)
    result = user_service.login(
        account=login_req.account,
        password_hash=login_req.password,
        timestamp=login_req.timestamp or "",
        equipment_no=login_req.equipment_no,
    )
    if not result:
        return web.json_response(
            create_error_response("Invalid credentials").to_dict(),
            status=401,
        )

    return web.json_response(
        LoginResponse(
            token=result.token,
            user_name=login_req.account,  # Or fetch real name if needed
            is_bind=result.is_bind,
            is_bind_equipment=result.is_bind_equipment,
            sold_out_count=0,
        ).to_dict()
    )


@routes.post("/api/terminal/user/bindEquipment")
@public_route
async def handle_bind_equipment(request: web.Request) -> web.Response:
    # Endpoint: POST /api/terminal/user/bindEquipment
    # Purpose: Bind the device to the account.
    req_data = await request.json()
    try:
        bind_req = BindEquipmentRequest.from_dict(req_data)
    except (MissingField, ValueError):
        return web.json_response(
            create_error_response("Missing data").to_dict(), status=400
        )

    user_service: UserService = request.app["user_service"]
    user_service.bind_equipment(bind_req.account, bind_req.equipment_no)
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
    user_vo = user_service.get_user_profile(account)
    if not user_vo:
        return web.json_response(
            create_error_response("User not found").to_dict(),
            status=404,
        )

    return web.json_response(
        UserQueryResponse(
            user=user_vo,
            is_user=True,
            # We don't necessarily know which equipment is asking, so we might omit or use a default
            # But technically valid responses often include it. Let's see if we can get it from context.
            # For now, omit or leave None as per VO.
            equipment_no=None,
        ).to_dict()
    )
