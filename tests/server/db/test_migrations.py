import asyncio
import shutil
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


@pytest.fixture
def alembic_config() -> Config:
    """Return the alembic config object."""
    # Locate alembic.ini in the supernote package
    # We assume the test is running in a dev environment where files exist on disk
    base_dir = Path(__file__).parent.parent.parent.parent
    ini_path = base_dir / "supernote" / "alembic.ini"
    if not ini_path.exists():
        # Fallback if structure is different (e.g. installed package)
        # But for dev tests, verify path
        pytest.fail(f"Could not find alembic.ini at {ini_path}")

    return Config(str(ini_path))


@pytest.fixture
async def migrated_db(tmp_path: Path, alembic_config: Config) -> str:
    """Copy the golden fixture to a temp file, run migrations, and return the DB URL."""
    # 1. Locate fixture
    fixture_path = Path("tests/fixtures/db_v1.sqlite").absolute()
    if not fixture_path.exists():
        pytest.fail(f"Fixture not found: {fixture_path}")

    # 2. Copy to tmp_path
    # specific fix for macOS /private/var symlinks
    tmp_path = tmp_path.resolve()
    db_path = tmp_path / "supernote.db"
    shutil.copy(fixture_path, db_path)

    # 3. Configure Alembic to use this DB
    # We use a sync driver for the migration step to avoid async complexities in the thread
    # and to bypass any potential aiosqlite path issues on macOS.
    migration_db_url = f"sqlite:///{db_path}"
    print(f"DEBUG: Migration URL: {migration_db_url}")

    # We need to set the main option in the config object
    # NOT in the file.
    alembic_config.set_main_option("sqlalchemy.url", migration_db_url)

    # 4. Run upgrade head
    # upgrading involves async operations if we were using async engine directly
    # but alembic commands are synchronous wrappers usually.
    # However, our env.py uses async_engine_from_config which needs an event loop.
    # Since we are in an async test, we need to be careful.
    # The standard Alembic command is blocking.
    # Let's run it in a thread to be safe and avoid event loop conflicts if any.

    await asyncio.to_thread(command.upgrade, alembic_config, "head")

    if not db_path.exists():
        pytest.fail("DB file disappeared after migration!")

    # Return the sync URL for the test to use
    return f"sqlite:///{db_path}"


def test_migration_upgrades_successfully(migrated_db: str) -> None:
    """Verify that we can upgrade the v1 database to head."""
    # If the fixture setup passed, the upgrade command succeeded.
    # Now let's verify we can connect and query the DB.

    engine = create_engine(migrated_db)
    with engine.connect() as conn:
        # Check if the 'alembic_version' table exists and has the head revision
        result = conn.execute(text("SELECT version_num FROM alembic_version"))
        version = result.scalar()
        assert version is not None

        # Check if a known table exists (e.g. users)
        result = conn.execute(text("SELECT count(*) FROM users"))
        count = result.scalar()
        assert count is not None
        assert count >= 0

    engine.dispose()
