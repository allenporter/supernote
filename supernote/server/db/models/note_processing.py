import time

from sqlalchemy import (
    BigInteger,
    Boolean,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from supernote.models.base import ProcessingStatus
from supernote.server.db.base import Base
from supernote.server.utils.unique_id import next_id


class NoteMetadataDO(Base):
    """Persisted notebook-level metadata extracted from .note files."""

    __tablename__ = "f_note_metadata"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)
    """Owner user ID."""

    file_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, index=True, nullable=False
    )
    """The numeric ID of the source file."""

    native_file_id: Mapped[str | None] = mapped_column(String, nullable=True)
    """Stable device-generated notebook identifier (<FILE_ID>)."""

    file_type: Mapped[str | None] = mapped_column(String, nullable=True)
    """4-byte container prefix ('note' or 'mark')."""

    equipment: Mapped[str | None] = mapped_column(String, nullable=True)
    """Hardware equipment identifier (<APPLY_EQUIPMENT>, e.g. 'A5X', 'N5', 'N6')."""

    signature: Mapped[str | None] = mapped_column(String, nullable=True)
    """Format version signature (e.g. 'SN_FILE_VER_20230015')."""

    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """Canvas width in pixels."""

    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """Canvas height in pixels."""

    total_pages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Total number of pages in the notebook."""

    recogn_language: Mapped[str | None] = mapped_column(String, nullable=True)
    """Handwriting recognition locale (<FILE_RECOGN_LANGUAGE>)."""

    is_realtime_recognition: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    """True when real-time handwriting recognition is enabled."""

    header_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    """Lossless JSON serialization of HeaderMetadata wire dictionary."""

    footer_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    """Lossless JSON serialization of FooterMetadata wire dictionary."""

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
        Index(
            "ix_f_note_metadata_user_native_file_id",
            "user_id",
            "native_file_id",
        ),
    )


class NotePageMetadataDO(Base):
    """Persisted per-page structural metadata, ink/drawable signals, and annotations."""

    __tablename__ = "f_note_page_metadata"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)
    """Owner user ID."""

    file_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, index=True, nullable=False
    )
    """The numeric ID of the source file."""

    page_index: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    """The 0-based index of the page in the notebook."""

    page_id: Mapped[str] = mapped_column(String, default="", nullable=False)
    """Stable unique page identifier (<PAGEID>), or empty string on legacy firmware."""

    page_style: Mapped[str | None] = mapped_column(String, nullable=True)
    """Raw Supernote PAGESTYLE template identifier (e.g. 'style_5mm_dots')."""

    style_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    """Custom background template MD5 hash (<PAGESTYLEMD5>), if present."""

    orientation: Mapped[str] = mapped_column(String, default="1000", nullable=False)
    """Page orientation code ('1000', '1090', '1180', '1270')."""

    recogn_status: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """On-device handwriting recognition status (<RECOGNSTATUS>)."""

    has_ink: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    """Whether any visible foreground layer on the page contains non-transparent ink."""

    has_drawables: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    """Whether the page contains visible foreground ink, text boxes, or vector graphics."""

    has_textbox: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    """Whether the page contains text box data (<PAGETEXTBOX> > 0)."""

    has_vector_graph: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    """Whether any visible foreground layer references vector graphics (<LAYERVECTORGRAPH> > 0)."""

    has_content: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    """Whether the page has foreground drawables or user-authored keywords, titles, or outgoing links."""

    page_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    """Lossless JSON serialization of PageMetadata wire dictionary."""

    keywords_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    """JSON list of NoteKeywordVO dicts anchored to this page."""

    titles_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    """JSON list of NoteTitleVO dicts anchored to this page."""

    links_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    """JSON list of NoteLinkVO dicts anchored to this page."""

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
        Index(
            "ix_f_note_page_metadata_user_file_page_id",
            "user_id",
            "file_id",
            "page_id",
        ),
    )


class NotePageContentDO(Base):
    """Cache for page-level content (OCR text, embeddings)."""

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
