import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class CoordinationService(ABC):
    """Interface for distributed locks and key-value state (tokens).

    This acts as a "redis-like" architecture for handling:
    1. Distributed Locks (prevent concurrent syncs).
    2. Session Tokens (Stateful JWT validity).
    """

    @abstractmethod
    async def acquire_lock(self, key: str, ttl: int) -> bool:
        """Try to acquire a lock. Returns True if successful."""
        pass

    @abstractmethod
    async def release_lock(self, key: str) -> None:
        """Release a lock."""
        pass

    @abstractmethod
    async def set_value(self, key: str, value: str, ttl: int | None = None) -> None:
        """Set a key-value pair with optional TTL."""
        pass

    @abstractmethod
    async def get_value(self, key: str) -> Optional[str]:
        """Get a value by key."""
        pass

    @abstractmethod
    async def delete_value(self, key: str) -> None:
        """Delete a key."""
        pass


class LocalCoordinationService(CoordinationService):
    """In-memory implementation for single-process instances (Supernote Lite).

    Uses asyncio.Lock and a Dict with expiry checks.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float]] = {}  # key -> (value, expiry_ts)
        self._global_lock = asyncio.Lock()

    def _cleanup(self):
        """Lazy cleanup of expired keys. Callers must hold lock."""
        now = time.time()
        keys_to_delete = [k for k, v in self._store.items() if v[1] < now]
        for k in keys_to_delete:
            del self._store[k]

    async def acquire_lock(self, key: str, ttl: int) -> bool:
        """Naive local lock imlpementation.

        This uses a single process lock and is not suitable for a distributed
        computing environment.
        """
        async with self._global_lock:
            self._cleanup()
            if key in self._store:
                return False

            expiry = time.time() + ttl
            # Store a dummy value for the lock
            self._store[key] = ("LOCKED", expiry)
            return True

    async def release_lock(self, key: str) -> None:
        """Release a lock."""
        async with self._global_lock:
            if key in self._store:
                del self._store[key]

    async def set_value(self, key: str, value: str, ttl: int | None = None) -> None:
        """Set a key-value pair with optional TTL."""
        async with self._global_lock:
            expiry = time.time() + (ttl if ttl else 31536000)  # Default 1 year
            self._store[key] = (value, expiry)

    async def get_value(self, key: str) -> Optional[str]:
        """Get a value by key."""
        async with self._global_lock:
            if key not in self._store:
                return None

            val, expiry = self._store[key]
            if time.time() > expiry:
                del self._store[key]
                return None
            return val

    async def delete_value(self, key: str) -> None:
        """Delete a key."""
        async with self._global_lock:
            if key in self._store:
                del self._store[key]
