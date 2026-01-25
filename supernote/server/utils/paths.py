import os
import uuid


def get_page_png_path(file_id: int, page_id: str) -> str:
    """Get the blob storage path for a page PNG."""
    return f"{file_id}/pages/{page_id}.png"


def get_file_chunk_path(object_name: str, part_number: int) -> str:
    """Generate a storage path for a file chunk."""
    return f"{object_name}.part.{part_number}"


def get_summary_id(file_basis: str) -> str:
    """Generate a unique identifier for an AI summary."""
    return f"{file_basis}-summary"


def get_transcript_id(file_basis: str) -> str:
    """Generate a unique identifier for an OCR transcript."""
    return f"{file_basis}-transcript"


def get_conversion_png_path(
    user_id: int, file_id: int, page_index: int, file_md5: str
) -> str:
    """Generate a storage path for a converted PNG page."""
    return f"conversions/{user_id}/{file_id}/page_{page_index}_{file_md5}.png"


def get_conversion_pdf_path(user_id: int, file_id: int, file_md5: str) -> str:
    """Generate a storage path for a converted PDF note."""
    return f"conversions/{user_id}/{file_id}/note_{file_md5}.pdf"


def generate_inner_name(filename: str, equipment_no: str | None) -> str:
    """Generate a system-of-record inner name.

    Format: {UUID}-{Tail}.{Ext}
    - UUID: Random UUID
    - Tail: Last 3 chars of equipment number (or full if short, default '000')
    """
    req_uuid = uuid.uuid4()
    ext = os.path.splitext(filename)[1]

    # Determine tail
    tail = "000"
    if equipment_no:
        tail = equipment_no[-3:] if len(equipment_no) >= 3 else equipment_no

    return f"{req_uuid}-{tail}{ext}"
