import pytest

from supernote.server.services.coordination import CoordinationService
from supernote.server.utils.rate_limit import RateLimiter, RateLimitExceeded


@pytest.mark.asyncio
async def test_rate_limiter_allow(coordination_service: CoordinationService) -> None:
    limiter = RateLimiter(coordination_service)

    # Should not raise
    await limiter.check("allow_key", limit=5, window=60)

    # Check it exists in DB (integration verification)
    # We need to know the bucket logic to verify key
    # But checking if check passes is enough for blackbox.
    pass


@pytest.mark.asyncio
async def test_rate_limiter_exceed(coordination_service: CoordinationService) -> None:
    limiter = RateLimiter(coordination_service)
    key = "exceed_key"
    limit = 2
    window = 60

    # 1. Allowed
    await limiter.check(key, limit, window)
    # 2. Allowed
    await limiter.check(key, limit, window)

    # 3. Exceeded
    with pytest.raises(RateLimitExceeded):
        await limiter.check(key, limit, window)


@pytest.mark.asyncio
async def test_rate_limiter_expiry(coordination_service: CoordinationService) -> None:
    from freezegun import freeze_time

    limiter = RateLimiter(coordination_service)
    key = "expiry:test"
    limit = 1
    window = 10

    # Freeze time at specific point
    with freeze_time("2023-01-01 12:00:00"):
        # 1. First attempt (Allowed)
        await limiter.check(key, limit, window)

        # 2. Second attempt (Blocked)
        with pytest.raises(RateLimitExceeded):
            await limiter.check(key, limit, window)

        # Move time forward by checking loop logic?
        # freezegun with context manager works for time.time() calls.

    with freeze_time("2023-01-01 12:00:11"):
        # 3. Should be allowed again (New bucket)
        await limiter.check(key, limit, window)
