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
    """Notebook-level structural metadata parsed from `.note` files (`f_note_metadata`).

    Keyed by `(user_id, file_id)` and populated by `PageHashingModule` on every
    file hash pass. `header_json` and `footer_json` store native
    `supernote.notebook.schema` `.to_wire_dict()` JSON so unrecognized firmware
    tags round-trip without coupling persistence to HTTP DTO schemas.
    """

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

    signature: Mapped[str | None] = mapped_column(String, nullable=True)
    """Format version signature (e.g. 'SN_FILE_VER_20230015')."""

    total_pages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Total number of pages in the notebook."""

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
    """Per-page structural metadata, ink/drawable flags, and wire annotations (`f_note_page_metadata`).

    Unlike `NotePageContentDO` (which is keyed by `(file_id, page_id)` so expensive
    OCR text and vector embeddings follow pages across reorders), `NotePageMetadataDO`
    is keyed by `(user_id, file_id, page_index)` across `0..total_pages - 1`. This
    guarantees deterministic ordered metadata for every page in the notebook,
    including legacy firmware notes that lack `<PAGEID>` (`page_id == ""`).
    `content_hash` caches the MD5 digest of `PageMetadata.to_wire_dict()` so unchanged
    pages skip bitmap ink decoding and redundant row updates on subsequent syncs.
    """

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

    content_hash: Mapped[str] = mapped_column(String, default="", nullable=False)
    """MD5 digest of the page's wire metadata block used to skip redundant bitmap ink scans."""

    page_style: Mapped[str | None] = mapped_column(String, nullable=True)
    """Raw Supernote PAGESTYLE template identifier (e.g. 'style_5mm_dots')."""

    has_ink: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    """Whether any visible foreground layer on the page contains non-transparent ink."""

    has_drawables: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    """Whether the page contains visible foreground ink, text boxes, or vector graphics."""

    page_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    """Lossless JSON serialization of PageMetadata wire dictionary."""

    keywords_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    """JSON list of KeywordMetadata wire dictionaries anchored to this page."""

    titles_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    """JSON list of TitleMetadata wire dictionaries anchored to this page."""

    links_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    """JSON list of LinkMetadata wire dictionaries anchored to this page."""

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
