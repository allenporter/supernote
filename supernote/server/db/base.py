"""Declarative SQLAlchemy 2.0 ORM base class with `AsyncAttrs` support.

All persistent database models in `supernote.server.db.models` inherit from `Base`.
"""

from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase


class Base(AsyncAttrs, DeclarativeBase):
    pass
