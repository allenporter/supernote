from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from supernote.server.db.base import Base


class UserDO(Base):
    """User database model."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)

    # We can add additional fields here in the future.

    def __repr__(self) -> str:
        return f"<UserDO(id={self.id}, username='{self.username}')>"
