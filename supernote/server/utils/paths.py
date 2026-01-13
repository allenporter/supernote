def get_page_png_path(file_id: int, page_index: int) -> str:
    """Get the blob storage path for a page PNG."""
    return f"{file_id}/pages/{page_index}.png"
