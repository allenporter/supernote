import importlib.resources
import logging
from pathlib import Path

import alembic.command
import alembic.config
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import OperationalError, ProgrammingError

logger = logging.getLogger(__name__)


def _heal_orphaned_v20_revision(db_url: str) -> None:
    """Detect and reconcile databases stamped with orphaned v0.20.0 revision c9a8b7c6d5e4.

    In v0.20.0, migration c9a8b7c6d5e4 altered task_id and task_list_id to String,
    but was superseded by d1e2f3a4b5c6 in subsequent releases. If detected, revert
    the column types back to BigInteger and reset alembic_version to b8e9c0d1e2f3
    so Alembic can cleanly upgrade forward to head.
    """
    sync_url = db_url.replace("+aiosqlite", "").replace("+asyncpg", "")
    engine = sa.create_engine(sync_url)
    try:
        with engine.connect() as conn:
            inspector = sa.inspect(conn)
            if "alembic_version" not in inspector.get_table_names():
                return

            current_revision = conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar()
            if current_revision != "c9a8b7c6d5e4":
                return

            logger.warning(
                "Detected orphaned v0.20.0 Alembic revision 'c9a8b7c6d5e4'. "
                "Reconciling database schema back to 'b8e9c0d1e2f3'..."
            )
            migration_context = MigrationContext.configure(conn)
            op = Operations(migration_context)

            with op.batch_alter_table("t_schedule_task") as batch_op:
                batch_op.alter_column(
                    "task_list_id", type_=sa.BigInteger(), existing_type=sa.String()
                )
                batch_op.alter_column(
                    "task_id", type_=sa.BigInteger(), existing_type=sa.String()
                )

            with op.batch_alter_table("t_schedule_task_group") as batch_op:
                batch_op.alter_column(
                    "task_list_id", type_=sa.BigInteger(), existing_type=sa.String()
                )

            conn.execute(
                sa.text(
                    "UPDATE alembic_version SET version_num = 'b8e9c0d1e2f3' WHERE version_num = 'c9a8b7c6d5e4'"
                )
            )
            conn.commit()
            logger.info(
                "Successfully reconciled schema to 'b8e9c0d1e2f3'; proceeding with migration to head."
            )
    except (OperationalError, ProgrammingError) as exc:
        logger.debug(
            "Skipping v0.20.0 migration healing due to database check error: %s", exc
        )
    finally:
        engine.dispose()


def run_migrations(db_url: str, target_revision: str = "head") -> None:
    """Run pending database migrations using Alembic.

    Args:
        db_url: The database connection URL to use for migrations.
               This overrides the url in alembic.ini to ensure we target
               the correct environment (prod, test, etc).
        target_revision: Revision to migrate to (default: "head").
    """
    # Locate alembic.ini inside the supernote package
    traversable = importlib.resources.files("supernote") / "alembic.ini"

    with importlib.resources.as_file(traversable) as ini_path:
        if not ini_path.exists():
            raise FileNotFoundError(f"Could not find alembic.ini at {ini_path}")

        alembic_cfg = alembic.config.Config(str(ini_path))

    # IMPORTANT: Override the URL with the one from the running application.
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    # Don't let alembic reset our carefully configured logging
    alembic_cfg.set_main_option("skip_logging_config", "true")

    # Ensure the database directory exists because sqlite won't create it
    if db_url.startswith("sqlite"):
        # Extract path from sqlite+aiosqlite:///path or sqlite:///path
        path_str = db_url.split(":///")[-1]
        if path_str != ":memory:":
            db_path = Path(path_str)
            db_path.parent.mkdir(parents=True, exist_ok=True)

    _heal_orphaned_v20_revision(db_url)

    logger.info("Running database migrations to %s...", target_revision)
    alembic.command.upgrade(alembic_cfg, target_revision)
    logger.info("Database migrations complete.")
