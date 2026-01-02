from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column

from supernote.server.db.base import Base


class KeyValueDO(Base):
    """Generic key-value store for coordination."""

    __tablename__ = "key_values"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)
    expiry: Mapped[float] = mapped_column(Float, index=True)

    def __repr__(self) -> str:
        return f"<KeyValueDO(key='{self.key}', expiry={self.expiry})>"
