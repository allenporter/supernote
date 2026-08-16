# Supernote Database Migrations & Revision History

This directory contains database schema and data migration scripts managed by [Alembic](https://alembic.sqlalchemy.org/).

## Revision History

| Revision ID | Date | Description |
| :--- | :--- | :--- |
| `0543a383957b` | 2026-08-01 | Initial database schema (`f_user_file`, `f_summary`, `f_user`, `t_schedule_task`, etc.) |
| `7a8291f043bc` | 2026-08-02 | Added links, sorting, and planner sort fields to `t_schedule_task` |
| `b8e9c0d1e2f3` | 2026-08-09 | Backfill missing `md5_hash`, `creation_time`, and `last_modified_time` in `f_summary` |

## Migration Guidelines & Conventions

1. **Location**: All revision scripts are stored in `supernote/alembic/versions/`.
2. **File Naming**: `<revision_id>_<snake_case_description>.py`.
3. **Data Backfills**: Non-destructive data backfills (such as calculating hashes or setting missing timestamps) should be executed inside `upgrade()` using `op.get_bind()` and SQLAlchemy `sa.text()` statements.
4. **Automatic Execution**: Database migrations run automatically during server startup in `supernote/server/app.py` via `run_migrations(config.db_url)`.

## Useful CLI Commands

### View Migration History
```bash
alembic -c supernote/alembic.ini history
```

### View Current Database Version
```bash
alembic -c supernote/alembic.ini current
```

### Create a New Migration Revision
```bash
alembic -c supernote/alembic.ini revision -m "description_of_changes"
```

### Manually Apply Migrations
```bash
alembic -c supernote/alembic.ini upgrade head
```
