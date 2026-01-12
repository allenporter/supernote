import time
from typing import Optional

from sqlalchemy import BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from supernote.server.db.base import Base
from supernote.server.utils.unique_id import next_id


class SummaryDO(Base):
    """Database model for both Summaries and Summary Groups."""

    __tablename__ = "f_summary"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_id)
    """Internal database ID."""

    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    """Owner user ID."""

    file_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, index=True, nullable=True
    )
    """The numeric ID of the source file in the cloud storage."""

    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """Display name of the summary or group."""

    unique_identifier: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    """Client-provided UUID for syncing."""

    parent_unique_identifier: Mapped[Optional[str]] = mapped_column(
        String, index=True, nullable=True
    )
    """The UUID of the parent Summary Group."""

    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    """The primary text content (OCR, markdown)."""

    source_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """Absolute path to the source file on the device."""

    data_source: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """Source of the data (e.g., 'OCR', 'USER', 'GEMINI')."""

    source_type: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    """Internal type indicator for the source."""

    is_summary_group: Mapped[bool] = mapped_column(default=False, nullable=False)
    """Flag indicating if this item is a folder/group or a leaf summary."""

    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """Additional text description of the summary."""

    tags: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """Comma-separated list of tag names."""

    md5_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """MD5 hash of the 'content' field."""

    extra_metadata: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    """JSON string containing additional structured metadata."""

    comment_str: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """Text comment associated with the summary."""

    comment_handwrite_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """Name of the handwriting file in OSS."""

    handwrite_inner_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """The innerName on OSS for the handwriting binary data."""

    handwrite_md5: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """MD5 hash of the handwriting binary data."""

    creation_time: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    """Original creation time in milliseconds."""

    last_modified_time: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    """Last modification time in milliseconds."""

    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False)
    """Soft-delete flag."""

    create_time: Mapped[int] = mapped_column(
        BigInteger, default=lambda: int(time.time() * 1000)
    )
    """System creation timestamp."""

    update_time: Mapped[int] = mapped_column(
        BigInteger,
        default=lambda: int(time.time() * 1000),
        onupdate=lambda: int(time.time() * 1000),
    )
    """System update timestamp."""

    author: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """Author of the summary."""


class SummaryTagDO(Base):
    """Database model for Summary Tags."""

    __tablename__ = "f_summary_tag"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_id)
    """Internal database ID."""

    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    """Owner user ID."""

    name: Mapped[str] = mapped_column(String, nullable=False)
    """Tag display name."""

    unique_identifier: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    """Tag UUID used for syncing."""

    create_time: Mapped[int] = mapped_column(
        BigInteger, default=lambda: int(time.time() * 1000)
    )
    """Creation timestamp."""


class NotePageStatusDO(Base):
    """Tracks the processing status of each page in a note file."""

    __tablename__ = "f_note_page_status"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_id)
    """Internal database ID."""

    file_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    """The numeric ID of the source file."""

    page_index: Mapped[int] = mapped_column(BigInteger, nullable=False)
    """The 0-based index of the page in the note."""

    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    """Hash of the page content (strokes) to detect changes."""

    png_status: Mapped[str] = mapped_column(String, default="PENDING", nullable=False)
    """Status of PNG generation (PENDING, PROCESSING, COMPLETED, FAILED)."""

    ocr_status: Mapped[str] = mapped_column(String, default="PENDING", nullable=False)
    """Status of OCR text extraction (PENDING, PROCESSING, COMPLETED, FAILED)."""

    embed_status: Mapped[str] = mapped_column(String, default="PENDING", nullable=False)
    """Status of embedding generation (PENDING, PROCESSING, COMPLETED, FAILED)."""

    retry_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    """Number of times processing has been retried."""

    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    """Error message from the last failure, if any."""

    create_time: Mapped[int] = mapped_column(
        BigInteger, default=lambda: int(time.time() * 1000)
    )
    """System creation timestamp."""

    update_time: Mapped[int] = mapped_column(
        BigInteger,
        default=lambda: int(time.time() * 1000),
        onupdate=lambda: int(time.time() * 1000),
    )
    """System update timestamp."""


class NotePageContentDO(Base):
    """Cache for page-level content (OCR text and embeddings)."""

    __tablename__ = "f_note_page_content"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_id)
    """Internal database ID."""

    file_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    """The numeric ID of the source file."""

    page_index: Mapped[int] = mapped_column(BigInteger, nullable=False)
    """The 0-based index of the page in the note."""

    text_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    """The extracted OCR text for this page."""

    embedding: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    """JSON string representation of the vector embedding."""

    create_time: Mapped[int] = mapped_column(
        BigInteger, default=lambda: int(time.time() * 1000)
    )
    """System creation timestamp."""

    update_time: Mapped[int] = mapped_column(
        BigInteger,
        default=lambda: int(time.time() * 1000),
        onupdate=lambda: int(time.time() * 1000),
    )
    """System update timestamp."""
