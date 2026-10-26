"""Route handlers for the Supernote Private Cloud HTTP and WebSocket APIs.

Routes are organized by functional domain using `aiohttp.web.RouteTableDef`:
- `supernote.server.routes.auth`: Challenge-response login, device binding, and JWT issuance.
- `supernote.server.routes.file_device`: Official Private Cloud device sync endpoints (`/api/file/2/*`, `/api/file/3/*`).
- `supernote.server.routes.file_web`: Web UI file management and recycle bin endpoints (`/api/file/*`).
- `supernote.server.routes.oss`: Signed Content-Addressable Storage (CAS) upload and download endpoints (`/api/oss/*`).
- `supernote.server.routes.schedule`: Tasks, task groups, sort orders, and RFC 5545 `.ics` feeds (`/api/file/schedule/*`, `/api/schedule/feed.ics`).
- `supernote.server.routes.summary`: Summaries and summary tags (`/api/file/*/summary*`).
- `supernote.server.routes.extended`: Knowledge Hub extensions for semantic search, transcripts, and task status (`/api/extended/*`).
- `supernote.server.routes.admin`: User provisioning, queue control, reprocessing, and storage integrity (`/api/admin/*`).
- `supernote.server.routes.system`: Server discovery and health endpoints.
"""

__all__ = [
    "admin",
    "auth",
    "decorators",
    "extended",
    "file_device",
    "file_web",
    "oss",
    "schedule",
    "summary",
    "system",
]
