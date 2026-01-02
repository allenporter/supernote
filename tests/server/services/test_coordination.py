import asyncio

import freezegun

from tests.server.services.fakes import FakeCoordinationService


async def test_key_expiry() -> None:
    with freezegun.freeze_time("2024-01-01 12:00:00") as frozen_time:
        service = FakeCoordinationService()
        await service.set_value("foo", "bar", ttl=1)

        assert await service.get_value("foo") == "bar"

        frozen_time.tick(1.1)
        assert await service.get_value("foo") is None


async def test_locks() -> None:
    service = FakeCoordinationService()
    lock_key = "user_1_lock"

    assert await service.acquire_lock(lock_key, ttl=5) is True
    # Fail to acquire again
    assert await service.acquire_lock(lock_key, ttl=5) is False

    # Release
    await service.release_lock(lock_key)

    # Acquire again
    assert await service.acquire_lock(lock_key, ttl=5) is True
