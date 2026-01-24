import time
from typing import Optional

from sqlalchemy import BigInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from supernote.models.base import ProcessingStatus
from supernote.server.db.base import Base
from supernote.server.utils.unique_id import next_id


class NotePageContentDO(Base):
    """Cache for page-level content (OCR text and embeddings)."""

    __tablename__ = "f_note_page_content"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_id)
    """Internal database ID."""

    file_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    """The numeric ID of the source file."""

    page_index: Mapped[int] = mapped_column(BigInteger, nullable=False)
    """The 0-based index of the page in the note."""

    page_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    """The stable unique identifier for the page (from .note file)."""

    content_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """MD5 hash of the page content (e.g. layers) to detect changes."""

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

    __table_args__ = (
        UniqueConstraint("file_id", "page_id", name="uq_note_page_content"),
    )


class SystemTaskDO(Base):
    """Generic system task tracking."""

    __tablename__ = "f_system_task"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_id)
    """Internal database ID."""

    file_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    """The numeric ID of the source file."""

    task_type: Mapped[str] = mapped_column(String, index=True, nullable=False)
    """Type of task (e.g., 'PNG', 'OCR', 'EMBED', 'SUMMARY')."""

    key: Mapped[str] = mapped_column(String, nullable=False)
    """Task key (e.g., 'page_1', 'global')."""

    status: Mapped[str] = mapped_column(
        String, default=ProcessingStatus.PENDING, nullable=False
    )
    """Current status (PENDING, PROCESSING, COMPLETED, FAILED)."""

    data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    """JSON string for task-specific data or output."""

    retry_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    """Number of retries."""

    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    """Error message from last failure."""

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

    __table_args__ = (
        UniqueConstraint("file_id", "task_type", "key", name="uq_system_task"),
    )
