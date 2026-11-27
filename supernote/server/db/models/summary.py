"""ORM models (`SummaryDO`, `SummaryTagDO`, and `SummaryTranscriptDO`) for AI and handwritten notebook summaries.

`SummaryDO` (`f_summary`) represents both summary groups (`is_summary_group=True`) and
individual summary/transcript items linked to a `UserFileDO.id`, storing Markdown text,
structured segment metadata (`metadata_str`), and optional handwriting blob references
(`handwrite_inner_name`). `SummaryTagDO` (`f_summary_tag`) stores user-defined tags.
`SummaryTranscriptDO` (`f_summary_transcript`, owned by `transcript`) stores OCR
transcripts for handwritten Digest `.mark` annotations keyed by `(user_id, summary_id)`.
Managed by `supernote.server.components.summary.service.SummaryService` and
`supernote.server.components.transcript.service.TranscriptService`. See `supernote.guides.summary_api`.
"""

import time

from sqlalchemy import BigInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from supernote.server.db.base import Base
from supernote.server.utils.unique_id import next_id


class SummaryDO(Base):
    """Database model for both Summaries and Summary Groups."""

    __tablename__ = "f_summary"
    __table_args__ = (
        UniqueConstraint("user_id", "unique_identifier", name="uq_f_summary_user_uuid"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_id)
    """Internal database ID."""

    user_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, index=True, nullable=False
    )
    """Owner user ID."""

    file_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    """The numeric ID of the source file in the cloud storage."""

    name: Mapped[str | None] = mapped_column(String, nullable=True)
    """Display name of the summary or group."""

    unique_identifier: Mapped[str] = mapped_column(String, nullable=False)
    """Client-provided UUID for syncing."""

    parent_unique_identifier: Mapped[str | None] = mapped_column(
        String, index=True, nullable=True
    )
    """The UUID of the parent Summary Group."""

    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The primary text content (OCR, markdown)."""

    source_path: Mapped[str | None] = mapped_column(String, nullable=True)
    """Absolute path to the source file on the device."""

    data_source: Mapped[str | None] = mapped_column(String, nullable=True)
    """Source of the data (e.g., 'OCR', 'USER', 'GEMINI')."""

    source_type: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """Internal type indicator for the source."""

    is_summary_group: Mapped[bool] = mapped_column(default=False, nullable=False)
    """Flag indicating if this item is a folder/group or a leaf summary."""

    description: Mapped[str | None] = mapped_column(String, nullable=True)
    """Additional text description of the summary."""

    tags: Mapped[str | None] = mapped_column(String, nullable=True)
    """Comma-separated list of tag names."""

    md5_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    """MD5 hash of the 'content' field."""

    extra_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)
    """JSON string containing additional structured metadata."""

    comment_str: Mapped[str | None] = mapped_column(String, nullable=True)
    """Text comment associated with the summary."""

    comment_handwrite_name: Mapped[str | None] = mapped_column(String, nullable=True)
    """Name of the handwriting file in OSS."""

    handwrite_inner_name: Mapped[str | None] = mapped_column(String, nullable=True)
    """The innerName on OSS for the handwriting binary data."""

    handwrite_md5: Mapped[str | None] = mapped_column(String, nullable=True)
    """MD5 hash of the handwriting binary data."""

    creation_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """Original creation time in milliseconds."""

    last_modified_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
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

    author: Mapped[str | None] = mapped_column(String, nullable=True)
    """Author of the summary."""


class SummaryTagDO(Base):
    """Database model for Summary Tags."""

    __tablename__ = "f_summary_tag"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "unique_identifier", name="uq_f_summary_tag_user_uuid"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_id)
    """Internal database ID."""

    user_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, index=True, nullable=False
    )
    """Owner user ID."""

    name: Mapped[str] = mapped_column(String, nullable=False)
    """Tag display name."""

    unique_identifier: Mapped[str] = mapped_column(String, nullable=False)
    """Tag UUID used for syncing."""

    create_time: Mapped[int] = mapped_column(
        BigInteger, default=lambda: int(time.time() * 1000)
    )
    """Creation timestamp."""


class SummaryTranscriptDO(Base):
    """OCR transcript for a Digest summary's handwritten `.mark` annotation (`f_summary_transcript`).

    Keyed by `(user_id, summary_id)` and owned by the `transcript` component.
    Stores `handwrite_md5` alongside `text_content` so callers can detect stale
    transcripts when a summary's handwriting blob changes without coupling
    `SummaryDO` synchronization to AI OCR state.
    """

    __tablename__ = "f_summary_transcript"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)
    """Owner user ID."""

    summary_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, nullable=False
    )
    """Numeric ID of the `SummaryDO` whose handwriting was transcribed."""

    handwrite_md5: Mapped[str] = mapped_column(String, nullable=False)
    """MD5 hash of the `.mark` handwriting blob that produced `text_content`."""

    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    """Extracted OCR transcript text (empty string if blank or illegible)."""

    model_id: Mapped[str | None] = mapped_column(String, nullable=True)
    """Identifier of the OCR model that produced `text_content`."""

    create_time: Mapped[int] = mapped_column(
        BigInteger, default=lambda: int(time.time() * 1000)
    )
    """System creation timestamp in milliseconds."""

    update_time: Mapped[int] = mapped_column(
        BigInteger,
        default=lambda: int(time.time() * 1000),
        onupdate=lambda: int(time.time() * 1000),
    )
    """System update timestamp in milliseconds."""
