# Schema Migration Guide

This project uses [Alembic](https://alembic.sqlalchemy.org/en/latest/) for database schema migrations.

## Overview

Alembic allows us to:
1.  **Version Control** our database schema.
2.  **Auto-Generate** migration scripts based on changes to our SQLAlchemy models.
3.  **Automatically Upgrade** the database on server startup.

## Workflow

### 1. Make Changes to Models

Edit the Python files in `supernote/models/` or `supernote/server/db/models/`.
For example, add a new field to `User`:

```python
# supernote/models/user.py
@dataclass
class UserVO(BaseResponse):
    # ...
    nickname: str | None = None  # <--- New field
```

### 2. Generate Migration Script

Run the following command to generate a new migration script:

```bash
script/db_revision "Add nickname to user"
```

This will create a new file in `alembic/versions/` (e.g., `alembic/versions/a1b2c3d4_add_nickname_to_user.py`).

> [!IMPORTANT]
> Always inspect the generated file!
> Alembic is good, but not perfect. Check that it detected your changes correctly and didn't drop anything unexpectedly.

### 3. Verify Locally

Apply the migration to your local database to make sure it works:

```bash
alembic -c supernote/alembic.ini upgrade head
```

### 4. Commit

Commit both your model changes and the new migration file to Git.

## Testing

We maintain a "Golden Fixture" to ensure that our migrations work correctly against older databases.

### Creating a Golden Fixture

To create a snapshot of the current database version (e.g., for Version 1):

1.  Start with a clean database.
2.  Run the server (which runs migrations).
3.  Add some dummy data (create a user, upload a file).
4.  Stop the server.
5.  Copy `storage/system/supernote.db` to `tests/fixtures/db_v1.sqlite`.

### Updating Regression Tests

When adding a new migration (e.g., Version 2), update `tests/server/db/test_migrations.py` to verify the upgrade path from `db_v1.sqlite` -> Version 2.

```python
# test_migrations.py
def test_upgrade_v1_to_latest(tmp_path):
    # Copy fixture to tmp_path
    # Run alembic upgrade head
    # Assert data is intact
```

## Troubleshooting

-   **"Target database is not up to date"**: This means your database is behind. Run `alembic -c supernote/alembic.ini upgrade head`.
-   **"Alembic detects changes even though I applied everything"**: This sometimes happens with types or constraints. You may need to manually adjust the migration script or the model definition to match exactly.
