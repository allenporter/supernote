import importlib.resources
import logging
from pathlib import Path

import alembic.command
import alembic.config

logger = logging.getLogger(__name__)


def run_migrations(db_url: str) -> None:
    """
    Run pending database migrations using Alembic.

    Args:
        db_url: The database connection URL to use for migrations.
               This overrides the url in alembic.ini to ensure we target
               the correct environment (prod, test, etc).
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

    logger.info("Running database migrations...")
    alembic.command.upgrade(alembic_cfg, "head")
    logger.info("Database migrations complete.")
