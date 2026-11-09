"""Conformance tests for database table schemas and multi-user scoping."""

from sqlalchemy import MetaData, UniqueConstraint

import supernote.server.db.models  # noqa: F401 - register all models on Base.metadata
from supernote.server.db.base import Base

# Internal SQLite and Alembic bookkeeping tables present in physical databases
INTERNAL_TABLES_ALLOWLIST = frozenset(
    {
        "alembic_version",
        "sqlite_sequence",
    }
)

# Tables that legitimately do not have a user_id column at all:
# - users: root user account table (primary key is id)
# - key_values: global server key-value coordination store
# - f_note_page_content: page OCR/embedding cache keyed by server-generated file_id
# - f_system_task: background processing queue keyed by server-generated file_id
TABLES_WITHOUT_USER_ID_ALLOWLIST = frozenset(
    {
        "users",
        "key_values",
        "f_note_page_content",
        "f_system_task",
    }
)

# Existing user-owned tables whose primary key is a server-generated ID (not client-supplied)
# and therefore does not include user_id in the primary key.
# All NEW user-owned tables must include user_id in their primary key.
TABLES_WITHOUT_USER_ID_IN_PK_ALLOWLIST = frozenset(
    {
        "devices",
        "login_records",
        "f_user_file",
        "f_recycle_file",
    }
)

# Existing user-owned tables with a globally unique column not scoped by user_id:
# - devices.equipment_no: hardware device serial number bound to a single account globally
UNSCOPED_UNIQUE_CONSTRAINT_ALLOWLIST = frozenset(
    {
        ("devices", ("equipment_no",)),
    }
)


def assert_metadata_user_id_conformance(metadata: MetaData) -> None:
    """Assert all tables in a SQLAlchemy MetaData conform to user_id scoping rules."""
    tables = {
        name: table
        for name, table in metadata.tables.items()
        if name not in INTERNAL_TABLES_ALLOWLIST
    }
    assert tables, "Expected SQLAlchemy metadata to have registered tables"

    missing_user_id: list[str] = []
    nullable_user_id: list[str] = []
    unscoped_pk_tables: list[str] = []
    unscoped_uniques: list[tuple[str, tuple[str, ...]]] = []

    for table_name, table in sorted(tables.items()):
        if table_name in TABLES_WITHOUT_USER_ID_ALLOWLIST:
            assert "user_id" not in table.c, (
                f"Table '{table_name}' has a 'user_id' column and should be removed "
                "from TABLES_WITHOUT_USER_ID_ALLOWLIST."
            )
            continue

        if "user_id" not in table.c:
            missing_user_id.append(table_name)
            continue

        if table.c["user_id"].nullable:
            nullable_user_id.append(table_name)

        pk_columns = {col.name for col in table.primary_key.columns}
        if table_name in TABLES_WITHOUT_USER_ID_IN_PK_ALLOWLIST:
            assert "user_id" not in pk_columns, (
                f"Table '{table_name}' now includes 'user_id' in its primary key and "
                "should be removed from TABLES_WITHOUT_USER_ID_IN_PK_ALLOWLIST."
            )
        elif "user_id" not in pk_columns:
            unscoped_pk_tables.append(f"{table_name} (pk={sorted(pk_columns)})")

        for col in table.columns:
            if col.unique and col.name != "user_id":
                key = (table_name, (col.name,))
                if key not in UNSCOPED_UNIQUE_CONSTRAINT_ALLOWLIST:
                    unscoped_uniques.append(key)

        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint):
                col_names = tuple(col.name for col in constraint.columns)
                if "user_id" not in col_names:
                    key = (table_name, col_names)
                    if key not in UNSCOPED_UNIQUE_CONSTRAINT_ALLOWLIST:
                        unscoped_uniques.append(key)

        for index in table.indexes:
            if index.unique:
                col_names = tuple(col.name for col in index.columns)
                if "user_id" not in col_names:
                    key = (table_name, col_names)
                    if key not in UNSCOPED_UNIQUE_CONSTRAINT_ALLOWLIST:
                        unscoped_uniques.append(key)

    assert not missing_user_id, (
        f"New tables must be scoped by a 'user_id' column: {missing_user_id}"
    )
    assert not nullable_user_id, (
        f"Table 'user_id' column must be non-nullable (nullable=False): {nullable_user_id}"
    )
    assert not unscoped_pk_tables, (
        "All new user-owned tables must include 'user_id' in their primary key so "
        f"client-supplied or synced IDs cannot collide across users: {unscoped_pk_tables}"
    )
    assert not unscoped_uniques, (
        "Unique constraints on user-owned tables must include 'user_id' to prevent "
        f"cross-user collisions: {unscoped_uniques}"
    )


def test_orm_models_user_id_conformance() -> None:
    """Verify ORM models registered on Base.metadata conform to user_id scoping rules."""
    assert_metadata_user_id_conformance(Base.metadata)
