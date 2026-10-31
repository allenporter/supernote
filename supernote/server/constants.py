"""Server-wide constants for VFS system directories, blob storage buckets, and limits.

Defines immutable Supernote folder names (`SYSTEM_ROOT_DIRECTORIES`,
`SYSTEM_CATEGORY_CONTAINER_MAP`), logical blob buckets (`USER_DATA_BUCKET`, `CACHE_BUCKET`),
upload size limits (`MAX_UPLOAD_SIZE` = 1 GB), SQLite busy timeouts, and the 30-day
recycle bin retention window (`RECYCLE_RETENTION_MS`).
"""

# Folders a Supernote device expects at fixed locations. Whether a folder is a
# system folder depends on where it is, see `VirtualFileSystem.is_system_directory`.
SYSTEM_ROOT_DIRECTORIES = {
    "EXPORT",
    "INBOX",
    "SCREENSHOT",
    "NOTE",
    "DOCUMENT",
}

# All system folder names regardless of location. Not suitable for deciding
# whether a folder is protected; use `VirtualFileSystem.is_system_directory`.
IMMUTABLE_SYSTEM_DIRECTORIES = SYSTEM_ROOT_DIRECTORIES | {
    "Note",
    "Document",
    "MyStyle",
}

# Category containers (hidden from web API)
CATEGORY_CONTAINERS = {"NOTE", "DOCUMENT"}

# Explicit mapping of system category subfolders to their parent container
SYSTEM_CATEGORY_CONTAINER_MAP = {
    "Note": "NOTE",
    "MyStyle": "NOTE",
    "Document": "DOCUMENT",
}

# Forced order and specific names for web API root (when flatten=True)
ORDERED_WEB_ROOT = ["Note", "Document"]

# Blob Storage Buckets
USER_DATA_BUCKET = "supernote-user-data"
CACHE_BUCKET = "supernote-cache"

# Maximum upload size for file uploads
MAX_UPLOAD_SIZE = 1024 * 1024 * 1024  # 1GB

# Database connection settings
SQLITE_TIMEOUT_SECONDS = 60.0

# Task processing queue settings
DEFAULT_PAGE_CONCURRENCY = 2

# Task status database write retry settings
DB_WRITE_MAX_RETRIES = 5
DB_WRITE_RETRY_BACKOFF_SECONDS = 0.1

# Retention window for soft-deleted recycle bin items and summaries (30 days)
RECYCLE_RETENTION_MS = 30 * 24 * 3600 * 1000
