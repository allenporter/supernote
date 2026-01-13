import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

from sqlalchemy import delete, select, text

from supernote.server.db.models.kv import KeyValueDO
from supernote.server.db.session import DatabaseSessionManager

logger = logging.getLogger(__name__)

DEFAULT_TTL = 31536000  # 1 year in seconds


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

    @abstractmethod
    async def pop_value(self, key: str) -> Optional[str]:
        """Get and delete a value atomically (if possible) or sequentially."""
        pass

    @abstractmethod
    async def increment(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        """Atomically increment a value. Returns new value."""
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
            expiry = time.time() + (ttl if ttl else DEFAULT_TTL)

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

    async def pop_value(self, key: str) -> Optional[str]:
        """Get and delete a value atomically."""
        async with self._session_manager.session() as session:
            # Traditional Select then Delete to avoid issues with RETURNING in some sqlite/alchemy versions
            stmt = select(KeyValueDO).where(KeyValueDO.key == key)
            result = await session.execute(stmt)
            kv = result.scalar_one_or_none()

            if not kv:
                return None

            value = kv.value
            expiry = kv.expiry
            await session.delete(kv)
            await session.commit()

            if time.time() > expiry:
                return None
            return str(value)

    async def increment(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        """Atomically increment a value. Returns the new value.

        If key does not exist, it is created with value `amount`.
        If key exists, its value is incremented.
        TTL is effective only if a new key is created.
        """
        async with self._session_manager.session() as session:
            now = time.time()
            expiry = now + (ttl if ttl else DEFAULT_TTL)

            # 1. Cleanup expired key if any (enforce fresh start if expired)
            stmt_del_expired = (
                delete(KeyValueDO)
                .where(KeyValueDO.key == key)
                .where(KeyValueDO.expiry < now)
            )
            await session.execute(stmt_del_expired)

            # 2. Upsert with RETURNING
            # DB stores value as String. We cast to int for math, then back to string.
            # On Conflict (key exists), we update value. We DO NOT update expiry (Redis behavior).

            sql = text("""
                INSERT INTO key_values (key, value, expiry)
                VALUES (:key, :initial_val, :expiry)
                ON CONFLICT(key) DO UPDATE SET
                    value = CAST(CAST(value AS INTEGER) + :amount AS TEXT)
                RETURNING value
            """)

            result = await session.execute(
                sql,
                {
                    "key": key,
                    "initial_val": str(amount),
                    "expiry": expiry,
                    "amount": amount,
                },
            )
            row = result.first()
            await session.commit()

            if row:
                return int(row[0])
            return amount  # Should not happen with RETURNING
