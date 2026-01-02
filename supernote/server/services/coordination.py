import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

from sqlalchemy import delete, select

from supernote.server.db.models.kv import KeyValueDO
from supernote.server.db.session import DatabaseSessionManager

logger = logging.getLogger(__name__)


class CoordinationService(ABC):
    """Interface for distributed locks and key-value state (tokens).

    This acts as a "redis-like" architecture for handling:
    1. Distributed Locks (prevent concurrent syncs).
    2. Session Tokens (Stateful JWT validity).
    """

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


class SqliteCoordinationService(CoordinationService):
    """SQLite-backed implementation for distributed locks and key-value state."""

    def __init__(self, session_manager: DatabaseSessionManager) -> None:
        self._session_manager = session_manager

    async def _cleanup(self) -> None:
        """Cleanup expired keys."""
        # This could be run periodically or on access.
        # For simplicity, we trust on-access checks or external cleanup jobs.
        pass

    async def set_value(self, key: str, value: str, ttl: int | None = None) -> None:
        """Set a key-value pair with optional TTL."""
        async with self._session_manager.session() as session:
            expiry = time.time() + (ttl if ttl else 31536000)  # Default 1 year

            # Upsert
            stmt = select(KeyValueDO).where(KeyValueDO.key == key)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                existing.value = value
                existing.expiry = expiry
            else:
                new_kv = KeyValueDO(key=key, value=value, expiry=expiry)
                session.add(new_kv)

            await session.commit()

    async def get_value(self, key: str) -> Optional[str]:
        """Get a value by key."""
        async with self._session_manager.session() as session:
            stmt = select(KeyValueDO).where(KeyValueDO.key == key)
            result = await session.execute(stmt)
            kv = result.scalar_one_or_none()

            if not kv:
                return None

            if time.time() > kv.expiry:
                # Lazy delete
                await session.execute(delete(KeyValueDO).where(KeyValueDO.key == key))
                await session.commit()
                return None

            return kv.value

    async def delete_value(self, key: str) -> None:
        """Delete a key."""
        async with self._session_manager.session() as session:
            stmt = delete(KeyValueDO).where(KeyValueDO.key == key)
            await session.execute(stmt)
            await session.commit()
