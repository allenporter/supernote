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

# Forced order and specific names for web API root (when flatten=True)
ORDERED_WEB_ROOT = ["Note", "Document"]

# Blob Storage Buckets
USER_DATA_BUCKET = "supernote-user-data"
CACHE_BUCKET = "supernote-cache"

# Maximum upload size for file uploads
MAX_UPLOAD_SIZE = 1024 * 1024 * 1024  # 1GB
