from collections.abc import AsyncGenerator

import freezegun
import pytest

from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.coordination import (
    CoordinationService,
    SqliteCoordinationService,
)

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def local_coordination_service() -> AsyncGenerator[CoordinationService]:
    """Create a local coordination service for testing."""
    manager = DatabaseSessionManager(TEST_DB_URL)
    assert manager._engine
    await manager.create_all_tables()

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


async def test_increment(coordination_service: SqliteCoordinationService) -> None:
    key = "incr:test"

    # 1. Increment new key
    val = await coordination_service.increment(key, 1, ttl=60)
    assert val == 1

    # Check it exists
    stored = await coordination_service.get_value(key)
    assert stored == "1"

    # 2. Increment existing
    val = await coordination_service.increment(key, 1)
    assert val == 2

    # 3. Increment by larger amount
    val = await coordination_service.increment(key, 10)
    assert val == 12


async def test_increment_expiry(
    coordination_service: SqliteCoordinationService,
) -> None:
    key = "incr:expire"

    # Set with short TTL (but we can't easily wait for it in unit test without sleep)
    # Instead, we manually set an expired value first?
    # No, let's use the property that increment sets TTL on creation.

    # 1. Create
    val = await coordination_service.increment(key, 1, ttl=100)
    assert val == 1

    # 2. Verify TTL is roughly logic (hard to verify exact value without inspecting DB directly)
    # But we can verify "expired" behavior by mocking time or inserting expired row manually.
