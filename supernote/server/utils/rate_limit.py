import time

from supernote.server.exceptions import RateLimitExceeded
from supernote.server.services.coordination import CoordinationService

# Constants for Rate Limiting
LIMIT_LOGIN_IP_MAX = 20
LIMIT_LOGIN_IP_WINDOW = 60  # 1 minute
LOGIN_KEY_IP = "login:ip"

LIMIT_LOGIN_ACCOUNT_MAX = 10
LIMIT_LOGIN_ACCOUNT_WINDOW = 60  # 1 minute
LOGIN_KEY_ACCOUNT = "login:account"

LIMIT_PW_RESET_MAX = 5
LIMIT_PW_RESET_WINDOW = 3600  # 1 hour
RESET_KEY_ACCOUNT = "reset:account"
RESET_KEY_IP = "reset:ip"


class RateLimiter:
    """Simple distributed rate limiter using Fixed Window Counter algorithm."""

    def __init__(self, coordination_service: CoordinationService):
        self._coordination_service = coordination_service

    async def check(self, key: str, limit: int, window: int) -> None:
        """Check if the action is allowed.

        Args:
            key: Unique identifier for the action (e.g. "login:ip:127.0.0.1")
            limit: Max allowed attempts per window
            window: Time window in seconds

        Raises:
            RateLimitExceeded: If the limit is exceeded.
        """
        # Fixed Window: bucket is defined by floor(time / window)
        now = int(time.time())
        bucket = now // window

        # Key includes the bucket so it auto-resets when window changes
        # e.g. "rate_limit:login:ip:127.0.0.1:167890"
        rate_key = f"rate_limit:{key}:{bucket}"

        # Increment
        # We set TTL to window * 2 to ensure we don't clutter DB, but enough to cover the window width.
        # Actually window size is enough + buffer.
        count = await self._coordination_service.increment(rate_key, 1, ttl=window + 60)

        if count > limit:
            raise RateLimitExceeded("Rate limit exceeded. Try again later.")
