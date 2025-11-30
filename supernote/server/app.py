import logging
import json
import time
import secrets
from aiohttp import web
from . import config

logger = logging.getLogger(__name__)


@web.middleware
async def trace_middleware(request, handler):
    # Skip reading body for upload endpoints to avoid consuming the stream
    # which breaks multipart parsing in the handler.
    if "/upload/data/" in request.path:
        return await handler(request)

    # Read body if present
    body_bytes = None
    if request.can_read_body:
        try:
            body_bytes = await request.read()
        except Exception as e:
            logger.error(f"Error reading body: {e}")
            body_bytes = b"<error reading body>"

    body_str = None
    if body_bytes:
        try:
            body_str = body_bytes.decode("utf-8", errors="replace")
            # Truncate body if it's too long (e.g. > 1KB)
            if len(body_str) > 1024:
                body_str = body_str[:1024] + "... (truncated)"
        except Exception:
            body_str = "<binary data>"

    # Log request details
    log_entry = {
        "timestamp": time.time(),
        "method": request.method,
        "url": str(request.url),
        "headers": dict(request.headers),
        "body": body_str,
    }

    try:
        with open(config.TRACE_LOG_FILE, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
            f.flush()
    except Exception as e:
        logger.error(f"Failed to write to trace log: {e}")

    logger.info(f"Trace: {request.method} {request.path} (Body: {len(body_bytes) if body_bytes else 0} bytes)")

    # Process request
    response = await handler(request)

    return response


async def handle_root(request):
    return web.Response(text="Supernote Private Cloud Server")


async def handle_query_server(request):
    # Endpoint: GET /api/file/query/server
    # Purpose: Device checks if the server is a valid Supernote Private Cloud instance.
    return web.json_response({"success": True})


async def handle_equipment_unlink(request):
    # Endpoint: POST /api/terminal/equipment/unlink
    # Purpose: Device requests to unlink itself from the account/server.
    # Since this is a private cloud, we can just acknowledge success.
    return web.json_response({"success": True})


async def handle_check_user_exists(request):
    # Endpoint: POST /api/official/user/check/exists/server
    # Purpose: Check if the user exists on this server.
    # For now, we'll assume any user exists to allow login to proceed.
    return web.json_response({"success": True})


async def handle_query_token(request):
    # Endpoint: POST /api/user/query/token
    # Purpose: Initial token check (often empty request)
    return web.json_response({"success": True})


async def handle_random_code(request):
    # Endpoint: POST /api/official/user/query/random/code
    # Purpose: Get challenge for password hashing
    random_code = secrets.token_hex(4)  # 8 chars
    timestamp = str(int(time.time() * 1000))
    
    return web.json_response({
        "success": True,
        "randomCode": random_code,
        "timestamp": timestamp
    })


async def handle_login(request):
    # Endpoint: POST /api/official/user/account/login/new
    # Purpose: Login with hashed password
    
    # Generate a dummy JWT-like token
    # In a real implementation, we would validate the password hash here
    token = f"eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.{secrets.token_urlsafe(32)}.{secrets.token_urlsafe(32)}"
    
    return web.json_response({
        "success": True,
        "token": token,
        "userName": "Supernote User",
        "isBind": "Y",
        "isBindEquipment": "Y",
        "soldOutCount": 0
    })


async def handle_bind_equipment(request):
    # Endpoint: POST /api/terminal/user/bindEquipment
    # Purpose: Bind the device to the account.
    # We can just acknowledge success.
    return web.json_response({"success": True})


async def handle_user_query(request):
    # Endpoint: POST /api/user/query
    # Purpose: Get user details.
    return web.json_response({
        "success": True,
        "user": {
            "userName": "Supernote User",
            "email": "test@example.com",
            "phone": "",
            "countryCode": "1",
            "totalCapacity": "25485312",
            "fileServer": "0",  # 0 for ufile (or local?), 1 for aws
            "avatarsUrl": "",
            "birthday": "",
            "sex": "",
        },
        "isUser": True,
        "equipmentNo": "SN123456" # Should probably match the request if possible, or be generic
    })


async def handle_sync_start(request):
    # Endpoint: POST /api/file/2/files/synchronous/start
    # Purpose: Start a file synchronization session.
    # Response: SynchronousStartLocalVO
    return web.json_response({
        "success": True,
        "equipmentNo": "SN123456", # Should match request
        "synType": True # True for normal sync, False for full re-upload
    })


async def handle_sync_end(request):
    # Endpoint: POST /api/file/2/files/synchronous/end
    # Purpose: End a file synchronization session.
    # Response: SynchronousEndLocalVO (likely just success)
    return web.json_response({"success": True})


async def handle_list_folder(request):
    # Endpoint: POST /api/file/2/files/list_folder
    # Purpose: List folders for sync selection.
    # Response: ListFolderLocalVO
    
    # We'll return a few dummy folders so the user can select them.
    # In a real implementation, this would list directories from the storage.
    
    current_time = int(time.time() * 1000)
    
    entries = [
        {
            "tag": "folder",
            "id": "1",
            "name": "Document",
            "path_display": "/Document",
            "parent_path": "/",
            "content_hash": "",
            "is_downloadable": True,
            "size": 0,
            "lastUpdateTime": current_time
        },
        {
            "tag": "folder",
            "id": "2",
            "name": "Note",
            "path_display": "/Note",
            "parent_path": "/",
            "content_hash": "",
            "is_downloadable": True,
            "size": 0,
            "lastUpdateTime": current_time
        },
        {
            "tag": "folder",
            "id": "3",
            "name": "Export",
            "path_display": "/Export",
            "parent_path": "/",
            "content_hash": "",
            "is_downloadable": True,
            "size": 0,
            "lastUpdateTime": current_time
        }
    ]
    
    return web.json_response({
        "success": True,
        "equipmentNo": "SN123456", # Should match request
        "entries": entries
    })


async def handle_capacity_query(request):
    # Endpoint: POST /api/file/2/users/get_space_usage
    # Purpose: Get storage capacity usage.
    # Response: CapacityLocalVO
    
    return web.json_response({
        "success": True,
        "equipmentNo": "SN123456", # Should match request
        "used": 1024 * 1024 * 100, # 100MB used
        "allocationVO": {
            "tag": "personal",
            "allocated": 1024 * 1024 * 1024 * 10 # 10GB total
        }
    })


async def handle_query_by_path(request):
    # Endpoint: POST /api/file/3/files/query/by/path_v3
    # Purpose: Check if a file exists by path.
    # Response: FileQueryByPathLocalVO
    
    # For now, we always say the file doesn't exist (entriesVO=None)
    # This should trigger the device to upload the file.
    
    return web.json_response({
        "success": True,
        "equipmentNo": "SN123456", # Should match request
        "entriesVO": None
    })


async def handle_csrf(request):
    # Endpoint: GET /api/csrf
    token = secrets.token_urlsafe(16)
    resp = web.Response(text="CSRF Token")
    resp.headers["X-XSRF-TOKEN"] = token
    return resp


async def handle_upload_apply(request):
    # Endpoint: POST /api/file/3/files/upload/apply
    # Purpose: Request to upload a file.
    # Response: FileUploadApplyLocalVO
    
    data = await request.json()
    file_name = data.get("fileName")
    
    # Construct a URL for the actual upload.
    # In a real implementation, this might be a signed S3 URL or a local endpoint.
    # For this private cloud, we'll point to a local upload endpoint we'll create.
    
    # We need to handle the actual file upload at this URL.
    # Let's define /api/file/upload/data/{filename}
    
    upload_url = f"http://{request.host}/api/file/upload/data/{file_name}"
    
    return web.json_response({
        "success": True,
        "equipmentNo": "SN123456", # Should match request
        "bucketName": "supernote-local",
        "innerName": file_name,
        "xAmzDate": "",
        "authorization": "",
        "fullUploadUrl": upload_url,
        "partUploadUrl": upload_url # Assuming simple upload for now
    })


async def handle_upload_data(request):
    # Endpoint: POST /api/file/upload/data/{filename}
    # Purpose: Receive the actual file content.
    
    filename = request.match_info['filename']
    
    # The device sends multipart/form-data
    # Note: trace_middleware might have consumed the body already if we are not careful.
    # But trace_middleware uses request.read() which caches the body, so it should be fine?
    # Actually, request.read() reads the whole body into memory.
    # request.multipart() expects to read from the stream.
    # If the body is already read, we might need to handle it differently.
    
    if request._read_bytes:
        # Body already read by middleware
        # We need to reconstruct a multipart reader or just parse it manually if possible.
        # However, aiohttp's multipart reader expects a stream.
        # Since we are in a "lite" server, maybe we can just skip the middleware for this route
        # or make the middleware smarter.
        # For now, let's try to use the standard multipart reader which might fail if stream is consumed.
        pass

    reader = await request.multipart()
    
    # Read the first part (which should be the file)
    field = await reader.next()
    if field.name == 'file':
        # In a real implementation, we would save this file to disk.
        # For now, we'll just read the bytes and discard them (or maybe log size).
        size = 0
        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            size += len(chunk)
        
        logger.info(f"Received upload for {filename}: {size} bytes")
    
    return web.Response(status=200)


async def handle_upload_finish(request):
    # Endpoint: POST /api/file/2/files/upload/finish
    # Purpose: Confirm upload completion.
    # Response: FileUploadFinishLocalVO
    
    data = await request.json()
    
    return web.json_response({
        "success": True,
        "equipmentNo": data.get("equipmentNo"),
        "path_display": data.get("path") + data.get("fileName"),
        "id": "12345", # Dummy ID
        "size": int(data.get("size", 0)),
        "name": data.get("fileName"),
        "content_hash": data.get("content_hash")
    })


def create_app():
    app = web.Application(middlewares=[trace_middleware])
    app.router.add_get("/", handle_root)
    app.router.add_get("/api/file/query/server", handle_query_server)
    app.router.add_get("/api/csrf", handle_csrf)
    app.router.add_post("/api/terminal/equipment/unlink", handle_equipment_unlink)
    app.router.add_post("/api/official/user/check/exists/server", handle_check_user_exists)
    app.router.add_post("/api/user/query/token", handle_query_token)
    app.router.add_post("/api/official/user/query/random/code", handle_random_code)
    app.router.add_post("/api/official/user/account/login/new", handle_login)
    app.router.add_post("/api/official/user/account/login/equipment", handle_login)
    app.router.add_post("/api/terminal/user/bindEquipment", handle_bind_equipment)
    app.router.add_post("/api/user/query", handle_user_query)
    app.router.add_post("/api/file/2/files/synchronous/start", handle_sync_start)
    app.router.add_post("/api/file/2/files/synchronous/end", handle_sync_end)
    app.router.add_post("/api/file/2/files/list_folder", handle_list_folder)
    app.router.add_post("/api/file/3/files/list_folder_v3", handle_list_folder)
    app.router.add_post("/api/file/2/users/get_space_usage", handle_capacity_query)
    app.router.add_post("/api/file/3/files/query/by/path_v3", handle_query_by_path)
    app.router.add_post("/api/file/3/files/upload/apply", handle_upload_apply)
    app.router.add_post("/api/file/2/files/upload/finish", handle_upload_finish)
    app.router.add_put("/api/file/upload/data/{filename}", handle_upload_data)
    app.router.add_post("/api/file/upload/data/{filename}", handle_upload_data) # Support POST just in case
    
    # Add a catch-all route to log everything
    app.router.add_route("*", "/{tail:.*}", handle_root)
    return app


def run(args):
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    web.run_app(app, host=config.HOST, port=config.PORT)
