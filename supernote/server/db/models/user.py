from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from supernote.server.db.base import Base

# Default quota in bytes - 10GB
DEFAULT_QUOTA = 10 * 1024 * 1024 * 1024


class UserDO(Base):
    """User database model."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)

    # Auth & Profile Fields
    password_md5: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(default=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar: Mapped[str | None] = mapped_column(String, nullable=True)
    total_capacity: Mapped[str] = mapped_column(String, default=str(DEFAULT_QUOTA))

    is_admin: Mapped[bool] = mapped_column(default=False)
    """Allows the user to perform admin actions, auto enabled for first user."""

    def __repr__(self) -> str:
        return f"<UserDO(id={self.id}, email='{self.email}')>"
