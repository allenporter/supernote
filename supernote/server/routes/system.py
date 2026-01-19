import secrets

from aiohttp import web

from supernote.models.base import BaseResponse
from supernote.models.system import ReferenceInfoVO, ReferenceRespVO

from .decorators import public_route

routes = web.RouteTableDef()

DEFAULT_PARAMS = {
    "MAX_ERR_COUNTS": "5",  # 5 errors
    "UPLOAD_MAX": "10",  # 10 files
    "FILE_MAX": "2147483648",  # 2GB
    "COPY_MAX": "50",  # 50 files
    "DOWNLOAD_MAX_NUMBER": "20",  # 20 files
    "FILE_TYPE": "note,pdf,mark,png,jpg,jpeg,bmp,gif,epub,txt,doc,docx,ppt,pptx,xls,xlsx,zip,tar.gz,rar",
}


@routes.get("/api/health")
@public_route
async def handle_health(request: web.Request) -> web.Response:
    return web.Response(text="Supernote Private Cloud Server")


@routes.post("/api/official/system/base/param")
@public_route
async def handle_base_param(request: web.Request) -> web.Response:
    # Endpoint: GET /api/official/system/base/param
    # Purpose: Device checks if the server is a valid Supernote Private Cloud instance.
    return web.json_response(
        ReferenceRespVO(
            param_list=[
                ReferenceInfoVO(name=k, value=v) for k, v in DEFAULT_PARAMS.items()
            ]
        ).to_dict()
    )


@routes.get("/api/file/query/server")
@public_route
async def handle_query_server(request: web.Request) -> web.Response:
    # Endpoint: GET /api/file/query/server
    # Purpose: Device checks if the server is a valid Supernote Private Cloud instance.
    return web.json_response(BaseResponse().to_dict())


@routes.get("/api/csrf")
@public_route
async def handle_csrf(request: web.Request) -> web.Response:
    # Endpoint: GET /api/csrf
    token = secrets.token_urlsafe(16)
    resp = web.Response(text="CSRF Token")
    resp.headers["X-XSRF-TOKEN"] = token
    return resp
