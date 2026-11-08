import time

from sqlalchemy import BigInteger, Boolean, String, Text, UniqueConstraint
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

    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    """MD5 hash of the page content (e.g. layers) to detect changes."""

    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The extracted OCR text for this page."""

    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    """JSON string representation of the vector embedding."""

    embedding_model: Mapped[str | None] = mapped_column(String, nullable=True)
    """Identifier of the model that produced the embedding."""

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

    data: Mapped[str | None] = mapped_column(Text, nullable=True)
    """JSON string for task-specific data or output."""

    retry_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    """Number of retries."""

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class RapidLogEntryDO(Base):
    """Structured Bullet Journal Rapid Logging entry extracted from a notebook page."""

    __tablename__ = "f_rapid_log_entry"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_id)
    """Internal database ID."""

    user_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, index=True, nullable=False
    )
    """The numeric ID of the owning user."""

    file_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    """The numeric ID of the source .note file."""

    page_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    """The page ID where this entry appeared."""

    page_index: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    """The 0-based index of the page in the note."""

    kind: Mapped[str] = mapped_column(String, index=True, nullable=False)
    """Rapid Log entry kind: TASK, EVENT, or NOTE."""

    normalized_text: Mapped[str] = mapped_column(String, nullable=False)
    """Normalized text key for idempotent matching across syncs and migrations."""

    text: Mapped[str] = mapped_column(Text, nullable=False)
    """Display text extracted from handwriting."""

    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Nested indented child lines under this entry."""

    task_state: Mapped[str | None] = mapped_column(String, nullable=True)
    """Task bullet state (INCOMPLETE, COMPLETED, MIGRATED_FORWARD, MIGRATED_SCHEDULED, CANCELLED), or None for EVENT/NOTE."""

    is_starred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    """Whether the entry has a critical '*' signifier."""

    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    """Whether the entry is crossed out ('~~...~~')."""

    page_date_ms: Mapped[int | None] = mapped_column(
        BigInteger, index=True, nullable=True
    )
    """Inferred UTC start-of-day page date timestamp (ms), if available."""

    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    """MD5 hash of the extracted entry fields and page anchor to detect handwritten edits."""

    schedule_task_id: Mapped[str | None] = mapped_column(
        String, index=True, nullable=True
    )
    """Owned ScheduleTaskDO.task_id for synced TASK entries, or None."""

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
        UniqueConstraint(
            "user_id",
            "file_id",
            "page_id",
            "kind",
            "normalized_text",
            name="uq_rapid_log_entry",
        ),
    )
