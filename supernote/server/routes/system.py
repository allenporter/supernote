import secrets
from aiohttp import web
from ..models.base import BaseResponse

routes = web.RouteTableDef()


@routes.get("/")
async def handle_root(request: web.Request) -> web.Response:
    return web.Response(text="Supernote Private Cloud Server")


@routes.get("/api/file/query/server")
async def handle_query_server(request: web.Request) -> web.Response:
    # Endpoint: GET /api/file/query/server
    # Purpose: Device checks if the server is a valid Supernote Private Cloud instance.
    return web.json_response(BaseResponse().to_dict())


@routes.get("/api/csrf")
async def handle_csrf(request: web.Request) -> web.Response:
    # Endpoint: GET /api/csrf
    token = secrets.token_urlsafe(16)
    resp = web.Response(text="CSRF Token")
    resp.headers["X-XSRF-TOKEN"] = token
    return resp
