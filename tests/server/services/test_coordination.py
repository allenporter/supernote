from typing import AsyncGenerator

import freezegun
import pytest

from supernote.server.db.base import Base
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.coordination import (
    CoordinationService,
    SqliteCoordinationService,
)

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def local_coordination_service() -> AsyncGenerator[CoordinationService, None]:
    """Create a local coordination service for testing."""
    manager = DatabaseSessionManager(TEST_DB_URL)
    assert manager._engine
    async with manager._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    service = SqliteCoordinationService(manager)
    yield service
    await manager.close()


async def test_key_expiry(local_coordination_service: CoordinationService) -> None:
    """Test key expiry."""
    with freezegun.freeze_time("2024-01-01 12:00:00"):
        await local_coordination_service.set_value("foo", "bar", ttl=15)

        assert await local_coordination_service.get_value("foo") == "bar"

    with freezegun.freeze_time("2024-01-01 12:00:16"):
        assert await local_coordination_service.get_value("foo") is None
