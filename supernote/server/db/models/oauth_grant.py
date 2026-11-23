"""SQLAlchemy ORM model for OAuth 2.1 client grants (`oauth_grants`).

This module defines `OAuthGrantDO`: one row per OAuth authorization a user approved
through `/login-bridge`. The row holds SHA-256 digests of the grant's current access
token and its refresh token, so verifying a Bearer token is one indexed lookup, no
plaintext token is stored, and deleting the row ends every token issued under it.
Managed by `supernote.server.services.user.UserService`.
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
    """IndieAuth client URL that requested access."""

    scopes: Mapped[str] = mapped_column(String(1024), nullable=False)
    """Granted scopes, space-separated as in OAuth."""

    access_token_hash: Mapped[str | None] = mapped_column(
        String(64), index=True, nullable=True, default=None
    )
    """SHA-256 of the current access token; NULL once revoked or never issued.

    A refresh replaces it, so each grant has at most one live access token."""

    access_expires_at: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    refresh_token_hash: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False
    )
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    last_used_at: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False)
    """When the refresh token, and so the grant, expires."""

    def __repr__(self) -> str:
        return f"<OAuthGrantDO(user_id={self.user_id}, id='{self.id}', client_id='{self.client_id}')>"
