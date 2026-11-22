"""SQLAlchemy ORM model for MCP OAuth client grants (`oauth_grants`).

This module defines `OAuthGrantDO`: one row per OAuth authorization a user approved
through `/login-bridge`. Access and refresh tokens minted for the authorization carry
the grant `id`, so deleting the row ends every token issued under it. Managed by
`supernote.server.services.user.UserService`. See `supernote.server.db.models`.
"""

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from supernote.server.db.base import Base


class OAuthGrantDO(Base):
    """OAuth client grant database model."""

    __tablename__ = "oauth_grants"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(2048), nullable=False)
    """IndieAuth client URL the user authorized."""

    scopes: Mapped[str] = mapped_column(String(1024), nullable=False)
    """Space-separated OAuth scopes granted."""

    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    last_used_at: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False)
    """Expiry of the grant's refresh token, after which the grant can mint no more tokens."""

    def __repr__(self) -> str:
        return (
            f"<OAuthGrantDO(user_id={self.user_id}, id='{self.id}', "
            f"client_id='{self.client_id}')>"
        )
