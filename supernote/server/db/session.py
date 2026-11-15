"""Asynchronous SQLAlchemy 2.0 session manager with SQLite WAL and PRAGMA tuning.

`DatabaseSessionManager` manages an `AsyncEngine` (`sqlite+aiosqlite`) configured with
`PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, and `PRAGMA busy_timeout`,
exposing an `@asynccontextmanager` `session()` helper that records database session
errors (`supernote.server.metrics.DB_SESSION_ERRORS_TOTAL`) and rolls back automatically on error:

```python
session_manager = DatabaseSessionManager("sqlite+aiosqlite:///supernote.db")

async with session_manager.session() as session:
    session.add(UserDO(email="user@example.com", password_md5="..."))
    await session.commit()

await session_manager.close()
```
"""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager, suppress
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
from supernote.server.exceptions import DatabaseError
from supernote.server.metrics import DB_SESSION_ERRORS_TOTAL

from .base import Base

ENGINE_KWARGS: dict[str, Any] = {
    # Set to True to enable verbose SQL logging
    "echo": False,
}

DEFAULT_SQLITE_PRAGMAS: dict[str, str | int] = {
    "journal_mode": "WAL",
    "synchronous": "NORMAL",
    "foreign_keys": "ON",
}


async def _rollback_quietly(session: AsyncSession) -> None:
    """Perform a best-effort session rollback without masking the active exception."""
    with suppress(SQLAlchemyError, OSError):
        await session.rollback()


class DatabaseSessionManager:
    """Database session manager."""

    def __init__(
        self,
        host: str,
        engine_kwargs: dict[str, Any] | None = None,
        sqlite_pragmas: Mapping[str, str | int] | None = None,
    ) -> None:
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
            assert self._engine is not None
            pragmas = {**DEFAULT_SQLITE_PRAGMAS, **(sqlite_pragmas or {})}
            pragma_statements = tuple(
                f"PRAGMA {name}={value}" for name, value in pragmas.items()
            )

            @event.listens_for(self._engine.sync_engine, "connect")
            def set_sqlite_pragma(
                dbapi_connection: Any, _connection_record: Any
            ) -> None:
                cursor = dbapi_connection.cursor()
                for stmt in pragma_statements:
                    cursor.execute(stmt)
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
        try:
            yield session
        except DatabaseError:
            DB_SESSION_ERRORS_TOTAL.inc()
            await _rollback_quietly(session)
            raise
        except SQLAlchemyError as err:
            DB_SESSION_ERRORS_TOTAL.inc()
            await _rollback_quietly(session)
            raise DatabaseError(str(err)) from err
        except BaseException:
            await _rollback_quietly(session)
            raise
        finally:
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
