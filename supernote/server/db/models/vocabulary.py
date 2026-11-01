import time

from sqlalchemy import BigInteger, Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from supernote.server.db.base import Base
from supernote.server.utils.unique_id import next_id

ROOT_SCOPE_ID = 0
"""Scope of a term that applies to every notebook (the root folder's id)."""


class VocabularyTermDO(Base):
    """A word or name that transcription prompts should prefer when the handwriting matches it."""

    __tablename__ = "f_vocabulary_term"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_id)
    """Internal database ID."""

    user_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, index=True, nullable=False
    )
    """Owner of the term."""

    term: Mapped[str] = mapped_column(String, nullable=False)
    """The term as it should be spelled."""

    scope_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=ROOT_SCOPE_ID
    )
    """Folder or notebook ID the term applies to; `ROOT_SCOPE_ID` for every notebook."""

    source: Mapped[str] = mapped_column(String, nullable=False)
    """Where the term came from (`VocabularySource`)."""

    origin_file_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """Notebook a harvested term was first found in; None for terms added by hand."""

    is_suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    """A removed harvested term, kept so that the next harvest does not add it back."""

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
        UniqueConstraint("user_id", "scope_id", "term", name="uq_vocabulary_term"),
    )
