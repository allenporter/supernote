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

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from supernote.server.exceptions import DatabaseError, SupernoteError

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
            engine_kwargs = ENGINE_KWARGS
        self._engine: AsyncEngine | None = create_async_engine(host, **engine_kwargs)
        self._sessionmaker: async_sessionmaker | None = async_sessionmaker(
            autocommit=False, bind=self._engine, expire_on_commit=False
        )

    async def close(self) -> None:
        """Close the database session manager."""
        if self._engine is None:
            raise DatabaseError("DatabaseSessionManager has been closed")
        await self._engine.dispose()
        self._engine = None
        self._sessionmaker = None

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session."""
        if self._sessionmaker is None:
            raise DatabaseError("DatabaseSessionManager has been closed")
        session = self._sessionmaker()
        try:
            yield session
        except SupernoteError:
            await session.rollback()
            raise
        except SQLAlchemyError as err:
            await session.rollback()
            raise DatabaseError(str(err)) from err
        except Exception:
            await session.rollback()
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
