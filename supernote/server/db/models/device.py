from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from supernote.server.db.base import Base


class DeviceDO(Base):
    """Device binding model."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    equipment_no: Mapped[str] = mapped_column(String, unique=True, index=True)

    def __repr__(self) -> str:
        return f"<DeviceDO(user_id={self.user_id}, equipment_no='{self.equipment_no}')>"
