"""Tests for session management.

These tests override the global sessionmanager for tests (if used by import
side-effects in other tests). Best practice is to test a fresh instance here.
"""

from sqlalchemy import text

from supernote.server.db.session import DatabaseSessionManager


async def test_session_manager_session() -> None:
    """Test that sessionmanager can provide a session."""
    manager = DatabaseSessionManager("sqlite+aiosqlite:///:memory:")

    async with manager.session() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1

    await manager.close()
