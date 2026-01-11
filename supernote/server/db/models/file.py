import time
from typing import Optional

from sqlalchemy import BigInteger, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from supernote.server.db.base import Base
from supernote.server.utils.unique_id import next_id


class UserFileDO(Base):
    """Represents the 'Virtual Filesystem' tree.

    Physical folder structure is NOT mirrored on disk.
    """

    __tablename__ = "f_user_file"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_id)
    """Unique ID."""

    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    """User ID."""

    directory_id: Mapped[int] = mapped_column(
        BigInteger, index=True, default=0, nullable=False
    )
    """Directory ID where 0 is the root directory."""

    file_name: Mapped[str] = mapped_column(String, nullable=False)
    """File name."""

    is_folder: Mapped[str] = mapped_column(String(1), default="N", nullable=False)
    """'Y' = Folder, 'N' = File."""

    size: Mapped[int] = mapped_column(BigInteger, default=0)
    """File size."""

    md5: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """Content hash."""

    storage_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    """Physical storage key (inner_name/UUID)."""

    is_active: Mapped[str] = mapped_column(String(1), default="Y", nullable=False)
    """'Y' = Active, 'N' = Deleted."""

    create_time: Mapped[int] = mapped_column(
        BigInteger, default=lambda: int(time.time() * 1000)
    )
    """Creation time in epoch milliseconds."""

    update_time: Mapped[int] = mapped_column(
        BigInteger,
        default=lambda: int(time.time() * 1000),
        onupdate=lambda: int(time.time() * 1000),
    )
    """Update time in epoch milliseconds."""

    __table_args__ = (
        # Index for "Listing children": where directory_id=? AND user_id=? AND is_active='Y'
        Index("idx_user_dir_active", "user_id", "directory_id", "is_active"),
    )


class CapacityDO(Base):
    """Tracks storage usage per user."""

    __tablename__ = "f_capacity"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    """User ID."""

    used_capacity: Mapped[int] = mapped_column(BigInteger, default=0)
    """Used capacity."""

    total_capacity: Mapped[int] = mapped_column(BigInteger, default=0)
    """Total capacity."""


class RecycleFileDO(Base):
    """Stores deleted files for restoration."""

    __tablename__ = "f_recycle_file"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=next_id)
    """Unique ID."""

    file_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    """Link back to original file ID."""

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    """User ID."""

    file_name: Mapped[str] = mapped_column(String, nullable=False)
    """File name."""

    size: Mapped[int] = mapped_column(BigInteger, default=0)
    """File size."""

    is_folder: Mapped[str] = mapped_column(String(1), default="N")
    """'Y' = Folder, 'N' = File."""

    delete_time: Mapped[int] = mapped_column(
        BigInteger, default=lambda: int(time.time() * 1000)
    )
    """Delete time in epoch milliseconds."""
