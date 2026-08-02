"""Server constants."""

# System directories that cannot be deleted or renamed
IMMUTABLE_SYSTEM_DIRECTORIES = {
    "Export",
    "Inbox",
    "Screenshot",
    "Note",
    "Document",
    "MyStyle",
    "NOTE",  # Category container
    "DOCUMENT",  # Category container
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
