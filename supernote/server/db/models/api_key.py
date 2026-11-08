from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from supernote.server.db.base import Base


class ApiKeyDO(Base):
    """Static Bearer API key database model."""

    __tablename__ = "api_keys"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    sha256_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    last_used_at: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    expires_at: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)

    def __repr__(self) -> str:
        return f"<ApiKeyDO(user_id={self.user_id}, id='{self.id}', name='{self.name}')>"
