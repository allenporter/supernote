from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from supernote.server.db.base import Base


class LoginRecordDO(Base):
    """Login history record."""

    __tablename__ = "login_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)

    # Details
    login_method: Mapped[str | None] = mapped_column(String, nullable=True)
    equipment: Mapped[str | None] = mapped_column(String, nullable=True)
    ip: Mapped[str | None] = mapped_column(String, nullable=True)
    create_time: Mapped[str] = mapped_column(String, index=True)  # Timestamp string

    def __repr__(self) -> str:
        return f"<LoginRecordDO(user_id={self.user_id}, time='{self.create_time}')>"
