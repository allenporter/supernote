"""Tests for session management.

These tests override the global sessionmanager for tests (if used by import
side-effects in other tests). Best practice is to test a fresh instance here.
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import DatabaseError, FileNotFound, QuotaExceeded


@pytest.fixture
async def seeded_manager(
    tmp_path: Path,
) -> AsyncGenerator[DatabaseSessionManager]:
    """Provide a file-backed DatabaseSessionManager seeded with a baseline row."""
    db_path = tmp_path / "session_metrics.db"
    manager = DatabaseSessionManager(f"sqlite+aiosqlite:///{db_path}")
    async with manager.session() as session:
        await session.execute(text("CREATE TABLE items (name TEXT PRIMARY KEY)"))
        await session.execute(text("INSERT INTO items (name) VALUES ('baseline')"))
        await session.commit()
    try:
        yield manager
    finally:
        await manager.close()


async def _fetch_items(manager: DatabaseSessionManager) -> list[str]:
    async with manager.session() as read_session:
        rows = await read_session.execute(text("SELECT name FROM items ORDER BY name"))
        return list(rows.scalars().all())


async def test_session_manager_session() -> None:
    """Test that sessionmanager can provide a session."""
    manager = DatabaseSessionManager("sqlite+aiosqlite:///:memory:")

    async with manager.session() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1

    await manager.close()


@pytest.mark.parametrize(
    ("exc_type", "message"),
    [
        (FileNotFound, "note missing"),
        (QuotaExceeded, "quota full"),
        (ValueError, "bad payload"),
    ],
)
async def test_session_non_db_error_rolls_back_without_incrementing_metric(
    seeded_manager: DatabaseSessionManager,
    exc_type: type[Exception],
    message: str,
) -> None:
    """Domain and application errors roll back uncommitted writes without incrementing DB_SESSION_ERRORS_TOTAL."""
    errors_before = (
        REGISTRY.get_sample_value("supernote_db_session_errors_total") or 0.0
    )

    with pytest.raises(exc_type, match=message):
        async with seeded_manager.session() as session:
            await session.execute(text("INSERT INTO items (name) VALUES ('transient')"))
            raise exc_type(message)

    assert await _fetch_items(seeded_manager) == ["baseline"]
    assert (
        REGISTRY.get_sample_value("supernote_db_session_errors_total") or 0.0
    ) == errors_before


async def test_session_sqlalchemy_error_rolls_back_and_increments_metric(
    seeded_manager: DatabaseSessionManager,
) -> None:
    """SQLAlchemyError rolls back, wraps in DatabaseError, and increments DB_SESSION_ERRORS_TOTAL."""
    errors_before = (
        REGISTRY.get_sample_value("supernote_db_session_errors_total") or 0.0
    )

    with pytest.raises(DatabaseError):
        async with seeded_manager.session() as session:
            await session.execute(text("INSERT INTO items (name) VALUES ('sa_err')"))
            await session.execute(text("SELECT * FROM missing_table"))

    assert await _fetch_items(seeded_manager) == ["baseline"]
    assert (
        REGISTRY.get_sample_value("supernote_db_session_errors_total")
        == errors_before + 1.0
    )


async def test_session_database_error_rolls_back_and_increments_metric(
    seeded_manager: DatabaseSessionManager,
) -> None:
    """Explicit DatabaseError rolls back uncommitted writes and increments DB_SESSION_ERRORS_TOTAL."""
    errors_before = (
        REGISTRY.get_sample_value("supernote_db_session_errors_total") or 0.0
    )

    with pytest.raises(DatabaseError, match="explicit db fault"):
        async with seeded_manager.session() as session:
            await session.execute(text("INSERT INTO items (name) VALUES ('db_err')"))
            raise DatabaseError("explicit db fault")

    assert await _fetch_items(seeded_manager) == ["baseline"]
    assert (
        REGISTRY.get_sample_value("supernote_db_session_errors_total")
        == errors_before + 1.0
    )


async def test_session_rollback_failure_still_propagates_original_error(
    seeded_manager: DatabaseSessionManager,
) -> None:
    """If best-effort rollback raises SQLAlchemyError, the original exception still propagates cleanly."""
    errors_before = (
        REGISTRY.get_sample_value("supernote_db_session_errors_total") or 0.0
    )
    active_before = REGISTRY.get_sample_value("supernote_db_sessions_active") or 0.0

    with pytest.raises(FileNotFound, match="still propagates"):
        async with seeded_manager.session() as session:
            session.rollback = AsyncMock(side_effect=SQLAlchemyError("broken conn"))  # type: ignore[method-assign]
            raise FileNotFound("still propagates")

    assert (
        REGISTRY.get_sample_value("supernote_db_session_errors_total") or 0.0
    ) == errors_before
    assert (
        REGISTRY.get_sample_value("supernote_db_sessions_active") or 0.0
    ) == active_before
