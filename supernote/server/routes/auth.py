from aiohttp import web
from supernote.server.models.base import BaseResponse
from supernote.server.models.auth import (
    RandomCodeResponse,
    LoginResponse,
    UserQueryResponse,
    UserCheckRequest,
)
from supernote.server.services.user import UserService

from .decorators import public_route

routes = web.RouteTableDef()


@routes.post("/api/terminal/equipment/unlink")
@public_route
async def handle_equipment_unlink(request: web.Request) -> web.Response:
    # Endpoint: POST /api/terminal/equipment/unlink
    # Purpose: Device requests to unlink itself from the account/server.
    user_service: UserService = request.app["user_service"]
    user_service.unlink_equipment("unknown")
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
        return web.json_response(
            BaseResponse(success=False, error_msg="User not found").to_dict()
        )


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
    user_service: UserService = request.app["user_service"]
    random_code, timestamp = user_service.generate_random_code("unknown")

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
    from ..models.auth import LoginRequest

    login_req = LoginRequest.from_dict(req_data)
    token = user_service.login(
        account=login_req.account,
        password_hash=login_req.password,
        timestamp=login_req.timestamp,
        equipment_no=login_req.equipmentNo,
    )
    return web.json_response(
        LoginResponse(
            token=token,
            user_name=login_req.account,
            is_bind="Y",
            is_bind_equipment="Y",
            sold_out_count=0,
        ).to_dict()
    )


@routes.post("/api/terminal/user/bindEquipment")
@public_route
async def handle_bind_equipment(request: web.Request) -> web.Response:
    # Endpoint: POST /api/terminal/user/bindEquipment
    # Purpose: Bind the device to the account.
    user_service: UserService = request.app["user_service"]
    user_service.bind_equipment("unknown", "unknown")
    return web.json_response(BaseResponse().to_dict())


@routes.post("/api/user/query")
async def handle_user_query(request: web.Request) -> web.Response:
    # Endpoint: POST /api/user/query
    # Purpose: Get user details.
    user_service: UserService = request.app["user_service"]
    account = request.get("user")
    if not account:
        return web.json_response(
            BaseResponse(success=False, error_msg="Unauthorized").to_dict(), status=401
        )
    user_vo = user_service.get_user_profile(account)
    if not user_vo:
        return web.json_response(
            BaseResponse(success=False, error_msg="User not found").to_dict(),
            status=404,
        )
    # Ensure user_name reflects the actual account
    return web.json_response(
        UserQueryResponse(
            user=user_vo,
            is_user=True,
            equipment_no="SN123456",
        ).to_dict()
    )
