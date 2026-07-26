"""Database session manager.

You may create a session manager then use it like this:

```
session_manager = DatabaseSessionManager("sqlite+aiosqlite:///supernote.db")
session_manager.connect()

async with session_manager.session() as session:
    session.add(User(username="user", password="password"))
    await session.commit()

session_manager.close()
```

"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from supernote.server.constants import SQLITE_TIMEOUT_SECONDS
from supernote.server.exceptions import DatabaseError, SupernoteError
from supernote.server.metrics import DB_SESSION_ERRORS_TOTAL, DB_SESSIONS_ACTIVE

from .base import Base

ENGINE_KWARGS: dict[str, Any] = {
    # Set to True to enable verbose SQL logging
    "echo": False,
}


class DatabaseSessionManager:
    """Database session manager."""

    def __init__(self, host: str, engine_kwargs: dict[str, Any] | None = None):
        """Initialize the database session manager."""
        if engine_kwargs is None:
            engine_kwargs = dict(ENGINE_KWARGS)
        else:
            engine_kwargs = dict(engine_kwargs)

        # Apply SQLite timeout connection parameter
        if "sqlite" in host:
            connect_args = engine_kwargs.setdefault("connect_args", {})
            if "timeout" not in connect_args:
                connect_args["timeout"] = SQLITE_TIMEOUT_SECONDS

        self._engine: AsyncEngine | None = create_async_engine(host, **engine_kwargs)
        self._sessionmaker: async_sessionmaker | None = async_sessionmaker(
            autocommit=False, bind=self._engine, expire_on_commit=False
        )

        # Enable WAL (Write-Ahead Logging) and Normal synchronous mode for SQLite
        if "sqlite" in host:

            @event.listens_for(self._engine.sync_engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()

    async def close(self) -> None:
        """Close the database session manager."""
        if self._engine is None:
            raise DatabaseError("DatabaseSessionManager has been closed")
        await self._engine.dispose()
        self._engine = None
        self._sessionmaker = None

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession]:
        """Get a database session."""
        if self._sessionmaker is None:
            raise DatabaseError("DatabaseSessionManager has been closed")
        session = self._sessionmaker()
        DB_SESSIONS_ACTIVE.inc()
        try:
            yield session
        except SupernoteError:
            DB_SESSION_ERRORS_TOTAL.inc()
            await session.rollback()
            raise
        except SQLAlchemyError as err:
            DB_SESSION_ERRORS_TOTAL.inc()
            await session.rollback()
            raise DatabaseError(str(err)) from err
        except Exception:
            DB_SESSION_ERRORS_TOTAL.inc()
            await session.rollback()
            raise
        finally:
            DB_SESSIONS_ACTIVE.dec()
            await session.close()

    async def create_all_tables(self) -> None:
        """Create all tables."""
        if self._engine is None:
            raise DatabaseError("DatabaseSessionManager has been closed")

        try:
            async with self._engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        except SQLAlchemyError as err:
            raise DatabaseError(f"Failed to create tables: {err}") from err
