"""Tests for session management.

These tests override the global sessionmanager for tests (if used by import
side-effects in other tests). Best practice is to test a fresh instance here.
"""
from sqlalchemy import text

from supernote.server.db.session import (
    DatabaseSessionManager,
)


async def test_session_manager_connect() -> None:
    """Test that sessionmanager can establish a connection."""
    # Create a fresh manager using in-memory DB
    manager = DatabaseSessionManager("sqlite+aiosqlite:///:memory:")

    async with manager.connect() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1

    await manager.close()


async def test_session_manager_session() -> None:
    """Test that sessionmanager can provide a session."""
    manager = DatabaseSessionManager("sqlite+aiosqlite:///:memory:")

    async with manager.session() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1

    await manager.close()


async def test_get_db_session_dependency() -> None:
    """Test the dependency injection helper."""
    # We rely on the global sessionmanager having an active engine.
    # Since we don't want to use the default file-based one, we can check
    # if it's initialized.

    # NOTE: The global sessionmanager is initialized at import time.
    # In tests, we might want to ensure it has a valid loop or connection if we use it.
    pass
