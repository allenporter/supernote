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
