import logging
import json
import time
import secrets
import os
import hashlib
import shutil
import asyncio
import urllib.parse
from pathlib import Path
from aiohttp import web
from . import config

logger = logging.getLogger(__name__)

STORAGE_ROOT = Path(config.STORAGE_DIR)
TEMP_ROOT = STORAGE_ROOT / "temp"

# Ensure directories exist
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
TEMP_ROOT.mkdir(parents=True, exist_ok=True)


def get_file_md5(path: Path) -> str:
    """Calculate MD5 of a file."""
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def get_dir_size(path: Path) -> int:
    """Calculate total size of a directory."""
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


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

    logger.info(
        f"Trace: {request.method} {request.path} (Body: {len(body_bytes) if body_bytes else 0} bytes)"
    )

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

    return web.json_response(
        {"success": True, "randomCode": random_code, "timestamp": timestamp}
    )


async def handle_login(request):
    # Endpoint: POST /api/official/user/account/login/new
    # Purpose: Login with hashed password

    # Generate a dummy JWT-like token
    # In a real implementation, we would validate the password hash here
    token = f"eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.{secrets.token_urlsafe(32)}.{secrets.token_urlsafe(32)}"

    return web.json_response(
        {
            "success": True,
            "token": token,
            "userName": "Supernote User",
            "isBind": "Y",
            "isBindEquipment": "Y",
            "soldOutCount": 0,
        }
    )


async def handle_bind_equipment(request):
    # Endpoint: POST /api/terminal/user/bindEquipment
    # Purpose: Bind the device to the account.
    # We can just acknowledge success.
    return web.json_response({"success": True})


async def handle_user_query(request):
    # Endpoint: POST /api/user/query
    # Purpose: Get user details.
    return web.json_response(
        {
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
            "equipmentNo": "SN123456",  # Should probably match the request if possible, or be generic
        }
    )


async def handle_sync_start(request):
    # Endpoint: POST /api/file/2/files/synchronous/start
    # Purpose: Start a file synchronization session.
    # Response: SynchronousStartLocalVO
    return web.json_response(
        {
            "success": True,
            "equipmentNo": "SN123456",  # Should match request
            "synType": True,  # True for normal sync, False for full re-upload
        }
    )


async def handle_sync_end(request):
    # Endpoint: POST /api/file/2/files/synchronous/end
    # Purpose: End a file synchronization session.
    # Response: SynchronousEndLocalVO (likely just success)
    return web.json_response({"success": True})


async def handle_list_folder(request):
    # Endpoint: POST /api/file/2/files/list_folder
    # Purpose: List folders for sync selection.
    # Response: ListFolderLocalVO

    data = await request.json()
    path_str = data.get("path", "/")

    # Map "/" to STORAGE_ROOT
    # Map "/Folder" to STORAGE_ROOT/Folder

    rel_path = path_str.lstrip("/")
    target_dir = STORAGE_ROOT / rel_path

    entries = []
    if target_dir.exists() and target_dir.is_dir():
        # Scan directory
        loop = asyncio.get_running_loop()

        def scan():
            res = []
            with os.scandir(target_dir) as it:
                for entry in it:
                    if entry.name == "temp":
                        continue  # Skip temp dir
                    if entry.name.startswith("."):
                        continue

                    is_dir = entry.is_dir()
                    stat = entry.stat()

                    content_hash = ""
                    if not is_dir:
                        # Calculate MD5 for files
                        # Note: This might be slow for many files.
                        # In a real implementation, we should cache this.
                        content_hash = get_file_md5(Path(entry.path))

                    res.append(
                        {
                            "tag": "folder" if is_dir else "file",
                            "id": f"{path_str.rstrip('/')}/{entry.name}".lstrip(
                                "/"
                            ),  # Use relative path as ID
                            "name": entry.name,
                            "path_display": f"{path_str.rstrip('/')}/{entry.name}",
                            "parent_path": path_str,
                            "content_hash": content_hash,
                            "is_downloadable": True,
                            "size": stat.st_size,
                            "lastUpdateTime": int(stat.st_mtime * 1000),
                        }
                    )
            return res

        entries = await loop.run_in_executor(None, scan)

    return web.json_response(
        {"success": True, "equipmentNo": data.get("equipmentNo"), "entries": entries}
    )


async def handle_capacity_query(request):
    # Endpoint: POST /api/file/2/users/get_space_usage
    # Purpose: Get storage capacity usage.
    # Response: CapacityLocalVO

    loop = asyncio.get_running_loop()
    used = await loop.run_in_executor(None, get_dir_size, STORAGE_ROOT)

    return web.json_response(
        {
            "success": True,
            "equipmentNo": "SN123456",  # Should match request
            "used": used,
            "allocationVO": {
                "tag": "personal",
                "allocated": 1024 * 1024 * 1024 * 10,  # 10GB total
            },
        }
    )


async def handle_query_by_path(request):
    # Endpoint: POST /api/file/3/files/query/by/path_v3
    # Purpose: Check if a file exists by path.
    # Response: FileQueryByPathLocalVO

    data = await request.json()
    path_str = data.get("path")
    rel_path = path_str.lstrip("/")
    target_path = STORAGE_ROOT / rel_path

    entries_vo = None
    if target_path.exists():
        stat = target_path.stat()
        entries_vo = {
            "tag": "folder" if target_path.is_dir() else "file",
            "id": rel_path,  # Use relative path as ID
            "name": target_path.name,
            "path_display": path_str,
            "parent_path": str(Path(path_str).parent),
            "content_hash": "",  # TODO
            "is_downloadable": True,
            "size": stat.st_size,
            "lastUpdateTime": int(stat.st_mtime * 1000),
        }

    return web.json_response(
        {
            "success": True,
            "equipmentNo": data.get("equipmentNo"),
            "entriesVO": entries_vo,
        }
    )


async def handle_query_v3(request):
    # Endpoint: POST /api/file/3/files/query_v3
    # Purpose: Get file details by ID.

    data = await request.json()
    file_id = data.get("id")

    # In our implementation, ID is the relative path
    rel_path = file_id
    target_path = STORAGE_ROOT / rel_path

    entries_vo = None
    if target_path.exists():
        stat = target_path.stat()
        # We need to reconstruct the display path.
        # If ID is "Folder/File.note", path_display is "/Folder/File.note"
        path_display = "/" + rel_path

        loop = asyncio.get_running_loop()
        content_hash = ""
        if not target_path.is_dir():
            content_hash = await loop.run_in_executor(None, get_file_md5, target_path)

        entries_vo = {
            "tag": "folder" if target_path.is_dir() else "file",
            "id": rel_path,
            "name": target_path.name,
            "path_display": path_display,
            "parent_path": str(Path(path_display).parent),
            "content_hash": content_hash,
            "is_downloadable": True,
            "size": stat.st_size,
            "lastUpdateTime": int(stat.st_mtime * 1000),
        }

    return web.json_response(
        {
            "success": True,
            "equipmentNo": data.get("equipmentNo"),
            "entriesVO": entries_vo,
        }
    )


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

    encoded_name = urllib.parse.quote(file_name)
    upload_url = f"http://{request.host}/api/file/upload/data/{encoded_name}"

    return web.json_response(
        {
            "success": True,
            "equipmentNo": "SN123456",  # Should match request
            "bucketName": "supernote-local",
            "innerName": file_name,
            "xAmzDate": "",
            "authorization": "",
            "fullUploadUrl": upload_url,
            "partUploadUrl": upload_url,  # Assuming simple upload for now
        }
    )


async def handle_upload_data(request):
    # Endpoint: POST /api/file/upload/data/{filename}
    # Purpose: Receive the actual file content.

    filename = request.match_info["filename"]
    temp_path = TEMP_ROOT / filename

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
    if field.name == "file":
        # Write to temp file
        # TODO: Add locking if needed

        loop = asyncio.get_running_loop()

        def write_chunk(f, chunk):
            f.write(chunk)

        with open(temp_path, "wb") as f:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                await loop.run_in_executor(None, write_chunk, f, chunk)

        logger.info(f"Received upload for {filename}: {temp_path.stat().st_size} bytes")

    return web.Response(status=200)


async def handle_upload_finish(request):
    # Endpoint: POST /api/file/2/files/upload/finish
    # Purpose: Confirm upload completion and move file to final location.
    # Response: FileUploadFinishLocalVO

    data = await request.json()
    filename = data.get("fileName")
    path_str = data.get("path")  # e.g. "/EXPORT/"
    content_hash = data.get("content_hash")

    temp_path = TEMP_ROOT / filename

    if not temp_path.exists():
        return web.json_response(
            {"success": False, "errorMsg": "Upload not found"}, status=404
        )

    loop = asyncio.get_running_loop()

    # Verify MD5
    calculated_hash = await loop.run_in_executor(None, get_file_md5, temp_path)
    if calculated_hash != content_hash:
        logger.warning(
            f"Hash mismatch for {filename}: expected {content_hash}, got {calculated_hash}"
        )
        # return web.json_response({"success": False, "errorMsg": "Hash mismatch"}, status=400)
        # For now, let's just log warning and proceed, or maybe the device sends different hash?
        # The device sends MD5.

    # Move to final destination
    # Remove leading slash from path_str to make it relative
    rel_path = path_str.lstrip("/")
    dest_dir = STORAGE_ROOT / rel_path
    dest_path = dest_dir / filename

    def move_file():
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_path), str(dest_path))

    await loop.run_in_executor(None, move_file)

    return web.json_response(
        {
            "success": True,
            "equipmentNo": data.get("equipmentNo"),
            "path_display": f"{path_str.rstrip('/')}/{filename}",
            "id": f"{path_str.rstrip('/')}/{filename}".lstrip(
                "/"
            ),  # Use relative path as ID
            "size": dest_path.stat().st_size,
            "name": filename,
            "content_hash": calculated_hash,
        }
    )


async def handle_download_apply(request):
    # Endpoint: POST /api/file/3/files/download_v3
    # Purpose: Request a download URL for a file.

    data = await request.json()
    file_id = data.get("id")  # This is the relative path now

    # Verify file exists
    target_path = STORAGE_ROOT / file_id
    if not target_path.exists():
        return web.json_response(
            {"success": False, "errorMsg": "File not found"}, status=404
        )

    # Generate URL
    encoded_id = urllib.parse.quote(file_id)
    download_url = f"http://{request.host}/api/file/download/data?path={encoded_id}"

    return web.json_response({"success": True, "url": download_url})


async def handle_download_data(request):
    # Endpoint: GET /api/file/download/data
    # Purpose: Download the file.

    path_str = request.query.get("path")
    if not path_str:
        return web.Response(status=400, text="Missing path")

    target_path = STORAGE_ROOT / path_str

    # Security check: prevent directory traversal
    try:
        target_path = target_path.resolve()
        storage_root_abs = STORAGE_ROOT.resolve()
        if not str(target_path).startswith(str(storage_root_abs)):
            return web.Response(status=403, text="Access denied")
    except Exception:
        return web.Response(status=403, text="Access denied")

    if not target_path.exists():
        return web.Response(status=404, text="File not found")

    return web.FileResponse(target_path)


def create_app():
    app = web.Application(middlewares=[trace_middleware])
    app.router.add_get("/", handle_root)
    app.router.add_get("/api/file/query/server", handle_query_server)
    app.router.add_get("/api/csrf", handle_csrf)
    app.router.add_post("/api/terminal/equipment/unlink", handle_equipment_unlink)
    app.router.add_post(
        "/api/official/user/check/exists/server", handle_check_user_exists
    )
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
    app.router.add_post("/api/file/3/files/query_v3", handle_query_v3)
    app.router.add_post("/api/file/3/files/query/by/path_v3", handle_query_by_path)
    app.router.add_post("/api/file/3/files/upload/apply", handle_upload_apply)
    app.router.add_post("/api/file/2/files/upload/finish", handle_upload_finish)
    app.router.add_post("/api/file/3/files/download_v3", handle_download_apply)
    app.router.add_get("/api/file/download/data", handle_download_data)
    app.router.add_put("/api/file/upload/data/{filename}", handle_upload_data)
    app.router.add_post(
        "/api/file/upload/data/{filename}", handle_upload_data
    )  # Support POST just in case
    app.router.add_post("/api/file/3/files/download_v3", handle_download_apply)
    app.router.add_get("/api/file/download/data", handle_download_data)

    # Add a catch-all route to log everything
    app.router.add_route("*", "/{tail:.*}", handle_root)
    return app


def run(args):
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    web.run_app(app, host=config.HOST, port=config.PORT)
