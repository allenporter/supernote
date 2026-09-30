"""Server constants."""

# Folders a Supernote device expects at fixed locations. Whether a folder is a
# system folder depends on where it is, see `VirtualFileSystem.is_system_directory`.
#
# The firmware creates these three root folders in capitals (EXPORT, INBOX,
# SCREENSHOT), so they are matched ignoring case.
CASE_VARIANT_SYSTEM_ROOTS = {
    "Export",
    "Inbox",
    "Screenshot",
}

# `NOTE` and `DOCUMENT` are matched exactly: `Note` is a different folder inside
# `NOTE`.
SYSTEM_ROOT_DIRECTORIES = CASE_VARIANT_SYSTEM_ROOTS | {"NOTE", "DOCUMENT"}

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
DEFAULT_PAGE_CONCURRENCY = 4

# Task status database write retry settings
DB_WRITE_MAX_RETRIES = 5
DB_WRITE_RETRY_BACKOFF_SECONDS = 0.1
