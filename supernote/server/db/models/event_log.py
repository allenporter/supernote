"""Database model for the append-only per-user domain event log."""

import time
from typing import Any

from sqlalchemy import JSON, BigInteger, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from supernote.server.db.base import Base


class UserEventDO(Base):
    """Append-only domain event record (`f_user_event`).

    Uses a non-recycled monotonic `seq` primary key so incremental sync clients,
    external AI agents, and UI views can share a single cursor spine.
    """

    __tablename__ = "f_user_event"
    __table_args__ = (
        Index("ix_f_user_event_user_seq", "user_id", "seq"),
        Index("ix_f_user_event_user_file_seq", "user_id", "related_file_id", "seq"),
        Index("ix_f_user_event_ts", "timestamp_ms"),
        {"sqlite_autoincrement": True},
    )

    seq: Mapped[int] = mapped_column(
        Integer().with_variant(BigInteger(), "postgresql"),
        primary_key=True,
        autoincrement=True,
    )
    """Strictly monotonic 64-bit cursor sequence number."""

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    """Owner user ID."""

    timestamp_ms: Mapped[int] = mapped_column(
        BigInteger, default=lambda: int(time.time() * 1000), nullable=False
    )
    """Event recording timestamp in UTC epoch milliseconds."""

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    """Namespaced domain event type (e.g. 'vfs.created', 'note.page_transcribed')."""

    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    """Originating actor identifier (e.g. 'device:<sn>', 'user:web', 'system:processor')."""

    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    """Target entity category ('file', 'note_page', 'schedule_task', 'summary', 'summary_tag')."""

    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    """Stable target entity identifier."""

    related_file_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """Associated VFS file ID when applicable."""

    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    """Structured delta payload dictionary."""
