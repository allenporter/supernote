import asyncio
import hashlib
import shutil
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from supernote.server.config import ServerConfig
from supernote.server.db.migrations import run_migrations


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
        assert version == "a2b3c4d5e6f7"

        # Check if a known table exists (e.g. users)
        result = conn.execute(text("SELECT count(*) FROM users"))
        count = result.scalar()
        assert count is not None
        assert count >= 0

    engine.dispose()


def test_summary_backfill_migration(migrated_db: str) -> None:
    """Verify that summary md5_hash, creation_time, and last_modified_time are backfilled by Alembic."""
    engine = create_engine(migrated_db)
    with engine.connect() as conn:
        # Verify items from db_v1_populated.sqlite were backfilled by Alembic upgrade head
        result = conn.execute(
            text(
                "SELECT id, content, creation_time, last_modified_time, md5_hash FROM f_summary"
            )
        )
        rows = result.fetchall()
        for row in rows:
            content, creation_time, last_modified_time, md5_hash = (
                row[1],
                row[2],
                row[3],
                row[4],
            )
            assert creation_time is not None
            assert last_modified_time is not None
            if content and md5_hash:
                assert md5_hash == hashlib.md5(content.encode("utf-8")).hexdigest()

    engine.dispose()


def test_summary_api_fixture_migration_backfill(
    tmp_path: Path, alembic_config: Config
) -> None:
    """Verify that Alembic upgrade head backfills the API-generated legacy fixture."""
    fixture_path = Path("tests/fixtures/db_v1_summary_api.sqlite").absolute()
    db_path = tmp_path / "summary_api_migrated.db"
    shutil.copy(fixture_path, db_path)

    migration_db_url = f"sqlite:///{db_path}"
    alembic_config.set_main_option("sqlalchemy.url", migration_db_url)
    command.upgrade(alembic_config, "head")

    engine = create_engine(migration_db_url)
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT id, content, creation_time, last_modified_time, md5_hash FROM f_summary"
            )
        )
        rows = result.fetchall()
        assert len(rows) >= 1
        for row in rows:
            content, creation_time, last_modified_time, md5_hash = (
                row[1],
                row[2],
                row[3],
                row[4],
            )
            assert creation_time is not None
            assert last_modified_time is not None
            assert md5_hash == hashlib.md5(content.encode("utf-8")).hexdigest()

    engine.dispose()


def test_orphaned_v0_20_0_migration_self_healing(tmp_path: Path) -> None:
    """Verify that a v0.20.0 database stamped with orphaned revision c9a8b7c6d5e4 heals and upgrades to head."""
    fixture_path = Path("tests/fixtures/db_v0_20_0_schedule.sqlite").absolute()
    db_path = tmp_path / "v0_20_0_healed.db"
    shutil.copy(fixture_path, db_path)

    migration_db_url = f"sqlite:///{db_path}"
    run_migrations(migration_db_url, "head")

    engine = create_engine(migration_db_url)
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == "a2b3c4d5e6f7"

        # Verify task columns and types
        tasks = conn.execute(
            text(
                "SELECT task_id, task_list_id, title, status FROM t_schedule_task ORDER BY task_id"
            )
        ).fetchall()
        assert len(tasks) == 3
        for row in tasks:
            assert isinstance(row[0], str)
            assert isinstance(row[1], str)

        titles = [row[2] for row in tasks]
        assert "Buy Milk Before Upgrade" in titles
        assert "Schedule Dentist Appointment" in titles
        assert "Task Created in v0.20.0" in titles

        # Verify group columns and types
        groups = conn.execute(
            text("SELECT task_list_id, title FROM t_schedule_task_group")
        ).fetchall()
        assert len(groups) >= 1
        assert isinstance(groups[0][0], str)

    engine.dispose()


def test_unify_schedule_ids_as_string_migration(
    tmp_path: Path, alembic_config: Config
) -> None:
    """Verify migration d4e5f6a7b8c9 backfills client string IDs into task_id and task_list_id and drops client_* columns."""
    db_path = tmp_path / "schedule_string_ids.db"
    shutil.copy(Path("tests/fixtures/db_v1.sqlite").absolute(), db_path)
    url = f"sqlite:///{db_path}"
    alembic_config.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_config, "c1d2e3f4a5b6")

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO t_schedule_task_group (task_list_id, client_task_list_id, user_id, title, create_time) "
                "VALUES (100, 'uuid-group-1', 1, 'Client Group', 1000), "
                "       (200, NULL, 1, 'Server Group', 2000)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO t_schedule_task "
                "(task_id, client_task_id, task_list_id, client_task_list_id, user_id, title, status, is_reminder_on, create_time, update_time) "
                "VALUES "
                "(1001, 'uuid-task-1', 100, NULL, 1, 'Task linked by int id to client group', 'needsAction', 0, 1000, 1000), "
                "(1002, NULL, 0, 'uuid-group-1', 1, 'Task linked by client group id', 'needsAction', 0, 1000, 1000), "
                "(1003, NULL, 200, NULL, 1, 'Task linked to server group', 'needsAction', 0, 1000, 1000)"
            )
        )

    command.upgrade(alembic_config, "d4e5f6a7b8c9")

    with engine.connect() as conn:
        groups = conn.execute(
            text(
                "SELECT task_list_id, title FROM t_schedule_task_group ORDER BY create_time"
            )
        ).fetchall()
        assert [tuple(r) for r in groups] == [
            ("uuid-group-1", "Client Group"),
            ("200", "Server Group"),
        ]

        tasks = conn.execute(
            text(
                "SELECT task_id, task_list_id, title FROM t_schedule_task ORDER BY title"
            )
        ).fetchall()
        assert [tuple(r) for r in tasks] == [
            ("1002", "uuid-group-1", "Task linked by client group id"),
            ("uuid-task-1", "uuid-group-1", "Task linked by int id to client group"),
            ("1003", "200", "Task linked to server group"),
        ]

    command.downgrade(alembic_config, "c1d2e3f4a5b6")
    engine.dispose()


def test_mixed_case_system_roots_are_merged(
    tmp_path: Path, alembic_config: Config
) -> None:
    """Export/Inbox/Screenshot become the firmware's EXPORT/INBOX/SCREENSHOT."""
    db_path = tmp_path / "mixed_case_roots.db"
    shutil.copy(Path("tests/fixtures/db_v1_summary_api.sqlite").absolute(), db_path)
    url = f"sqlite:///{db_path}"
    alembic_config.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_config, "68964804740d")

    engine = create_engine(url)

    def add(
        id: int, parent: int, name: str, folder: bool = False, md5: str = ""
    ) -> None:
        conn.execute(
            text(
                "INSERT INTO f_user_file (id, user_id, directory_id, file_name, "
                "is_folder, size, md5, is_active, create_time, update_time) "
                "VALUES (:id, 1, :parent, :name, :folder, 0, :md5, 'Y', 0, 0)"
            ),
            {
                "id": id,
                "parent": parent,
                "name": name,
                "folder": "Y" if folder else "N",
                "md5": md5 or None,
            },
        )

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT file_name, id FROM f_user_file "
                "WHERE user_id = 1 AND directory_id = 0"
            )
        ).fetchall()
        roots = {name: id for name, id in rows}
        export = roots["Export"]
        add(9000, 0, "EXPORT", folder=True)
        add(9001, export, "only-old.pdf", md5="a")
        add(9002, export, "same.pdf", md5="b")
        add(9003, 9000, "same.pdf", md5="b")
        add(9004, export, "clash.pdf", md5="c")
        add(9005, 9000, "clash.pdf", md5="d")
        add(9006, export, "Sub", folder=True)
        add(9007, 9006, "x.txt", md5="e")
        add(9008, 9000, "Sub", folder=True)
        add(9009, 9008, "y.txt", md5="f")
        add(9010, 9000, "clash (1).pdf", md5="g")
        add(9011, export, "Sub", md5="h")

    command.upgrade(alembic_config, "head")

    with engine.connect() as conn:

        def active(parent: int) -> dict[str, tuple[int, str | None]]:
            rows = conn.execute(
                text(
                    "SELECT file_name, id, md5 FROM f_user_file WHERE user_id = 1 "
                    "AND directory_id = :parent AND is_active = 'Y'"
                ),
                {"parent": parent},
            ).fetchall()
            return {name: (id, md5) for name, id, md5 in rows}

        root = active(0)
        assert set(root) == {"DOCUMENT", "EXPORT", "INBOX", "NOTE", "SCREENSHOT"}
        # A root folder with no uppercase twin is renamed in place.
        assert root["INBOX"][0] == roots["Inbox"]
        assert root["EXPORT"][0] == 9000

        files = {k: v for k, v in active(9000).items() if k != "Sub"}
        assert files == {
            "only-old.pdf": (9001, "a"),
            "same.pdf": (9003, "b"),
            "same (1).pdf": (9002, "b"),
            "clash.pdf": (9005, "d"),
            "clash (1).pdf": (9010, "g"),
            "clash (2).pdf": (9004, "c"),
        }
        # A file and a folder may share a name, so neither is renamed.
        subs = conn.execute(
            text(
                "SELECT id, is_folder FROM f_user_file WHERE directory_id = 9000 "
                "AND file_name = 'Sub' AND is_active = 'Y' ORDER BY id"
            )
        ).fetchall()
        assert [tuple(r) for r in subs] == [(9008, "Y"), (9011, "N")]
        assert set(active(9008)) == {"x.txt", "y.txt"}

    # Merged folders cannot be split again, so a downgrade leaves them as they are.
    command.downgrade(alembic_config, "68964804740d")
    with engine.connect() as conn:
        assert set(active(0)) == {"DOCUMENT", "EXPORT", "INBOX", "NOTE", "SCREENSHOT"}

    engine.dispose()


def test_mixed_case_system_roots_autorename_when_src_has_numbered_sibling(
    tmp_path: Path, alembic_config: Config
) -> None:
    """Renaming clash.pdf -> clash (1).pdf must not collide with an existing clash (1).pdf in Export."""
    db_path = tmp_path / "mixed_case_src_numbered.db"
    shutil.copy(Path("tests/fixtures/db_v1_summary_api.sqlite").absolute(), db_path)
    url = f"sqlite:///{db_path}"
    alembic_config.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_config, "68964804740d")

    engine = create_engine(url)

    def add(
        id: int, parent: int, name: str, folder: bool = False, md5: str = ""
    ) -> None:
        conn.execute(
            text(
                "INSERT INTO f_user_file (id, user_id, directory_id, file_name, "
                "is_folder, size, md5, is_active, create_time, update_time) "
                "VALUES (:id, 1, :parent, :name, :folder, 0, :md5, 'Y', 0, 0)"
            ),
            {
                "id": id,
                "parent": parent,
                "name": name,
                "folder": "Y" if folder else "N",
                "md5": md5 or None,
            },
        )

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT file_name, id FROM f_user_file "
                "WHERE user_id = 1 AND directory_id = 0"
            )
        ).fetchall()
        roots = {name: id for name, id in rows}
        export = roots["Export"]

        add(9000, 0, "EXPORT", folder=True)
        # Export has clash.pdf (created first) and clash (1).pdf (created second),
        # while EXPORT only has clash.pdf.
        add(9001, export, "clash.pdf", md5="a")
        add(9002, export, "clash (1).pdf", md5="b")
        add(9003, 9000, "clash.pdf", md5="c")

    command.upgrade(alembic_config, "head")

    with engine.connect() as conn:
        active_rows = conn.execute(
            text(
                "SELECT file_name, id, md5 FROM f_user_file WHERE user_id = 1 "
                "AND directory_id = 9000 AND is_active = 'Y' ORDER BY id"
            )
        ).fetchall()
        names = [r.file_name for r in active_rows]
        assert len(names) == len(set(names)), (
            f"Duplicate active filenames in EXPORT: {names}"
        )
        assert {r.file_name: (r.id, r.md5) for r in active_rows} == {
            "clash.pdf": (9003, "c"),
            "clash (1).pdf": (9002, "b"),
            "clash (2).pdf": (9001, "a"),
        }

    engine.dispose()


def test_mixed_case_system_roots_deletes_retired_folders_and_reparents_recycled(
    tmp_path: Path, alembic_config: Config
) -> None:
    """Merging roots deletes emptied folders, preserves all files, and reparents recycled items."""
    db_path = tmp_path / "mixed_case_dependents.db"
    shutil.copy(Path("tests/fixtures/db_v1_summary_api.sqlite").absolute(), db_path)
    url = f"sqlite:///{db_path}"
    alembic_config.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_config, "68964804740d")

    engine = create_engine(url)

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT file_name, id FROM f_user_file "
                "WHERE user_id = 1 AND directory_id = 0"
            )
        ).fetchall()
        roots = {name: id for name, id in rows}
        export = roots["Export"]

        conn.execute(
            text(
                "INSERT INTO f_user_file (id, user_id, directory_id, file_name, "
                "is_folder, size, md5, storage_key, is_active, create_time, update_time) "
                "VALUES "
                "(9000, 1, 0, 'EXPORT', 'Y', 0, NULL, NULL, 'Y', 0, 0), "
                "(9002, 1, :export, 'same.note', 'N', 100, 'b', 'blobs/b', 'Y', 0, 0), "
                "(9003, 1, 9000, 'same.note', 'N', 100, 'b', 'blobs/b', 'Y', 0, 0), "
                "(9015, 1, :export, 'recycled.pdf', 'N', 50, 'r', 'blobs/r', 'N', 0, 0)"
            ),
            {"export": export},
        )
        conn.execute(
            text(
                "INSERT INTO f_recycle_file (id, user_id, file_id, file_name, size, is_folder, delete_time) "
                "VALUES (5001, 1, 9015, 'recycled.pdf', 50, 'N', 0)"
            )
        )

    command.upgrade(alembic_config, "head")

    with engine.connect() as conn:
        # 1. Emptied mixed-case folder (export) is hard-deleted, leaving no zombie inactive folder.
        retired_export = conn.execute(
            text("SELECT id FROM f_user_file WHERE id = :export"),
            {"export": export},
        ).scalar()
        assert retired_export is None

        # 2. Both files are kept active in EXPORT (9000) via autorename; no file is deleted.
        active_files = conn.execute(
            text(
                "SELECT file_name, id FROM f_user_file WHERE user_id = 1 "
                "AND directory_id = 9000 AND is_active = 'Y'"
            )
        ).fetchall()
        assert {r.file_name: r.id for r in active_files} == {
            "same.note": 9003,
            "same (1).note": 9002,
        }

        # 3. Recycled item from Export is reparented to active EXPORT (9000) so restore works.
        recycled_parent_id = conn.execute(
            text("SELECT directory_id FROM f_user_file WHERE id = 9015")
        ).scalar()
        assert recycled_parent_id == 9000

    engine.dispose()


def test_embedding_model_migration_backfill(
    tmp_path: Path, alembic_config: Config
) -> None:
    """Verify migration c1d2e3f4a5b6 adds embedding_model and backfills from startup ServerConfig."""
    db_path = tmp_path / "embedding_model_backfill.db"
    shutil.copy(Path("tests/fixtures/db_v1.sqlite").absolute(), db_path)
    url = f"sqlite:///{db_path}"
    alembic_config.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_config, "b7397248a96b")

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO f_note_page_content "
                "(id, file_id, page_index, page_id, content_hash, text_content, embedding, create_time, update_time) "
                "VALUES "
                "(9001, 1001, 0, 'p0', 'h0', 'text with embedding', '[0.1, 0.2]', 0, 0), "
                "(9002, 1001, 1, 'p1', 'h1', 'text without embedding', NULL, 0, 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO f_system_task "
                "(id, file_id, task_type, key, status, data, retry_count, create_time, update_time) "
                "VALUES "
                "(9101, 1001, 'EMBEDDING_GENERATION', 'page_p0', 'COMPLETED', NULL, 0, 0, 0), "
                "(9102, 1001, 'OCR_EXTRACTION', 'page_p0', 'COMPLETED', NULL, 0, 0, 0)"
            )
        )

    run_migrations(
        url,
        "c1d2e3f4a5b6",
        config=ServerConfig(gemini_embedding_model="fake-embedding-v1"),
    )

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT page_index, embedding_model FROM f_note_page_content "
                "WHERE file_id = 1001 ORDER BY page_index"
            )
        ).fetchall()
        assert [tuple(r) for r in rows] == [
            (0, "fake-embedding-v1"),
            (1, None),
        ]
        task_rows = conn.execute(
            text(
                "SELECT task_type, data FROM f_system_task "
                "WHERE file_id = 1001 ORDER BY id"
            )
        ).fetchall()
        assert [tuple(r) for r in task_rows] == [
            ("EMBEDDING_GENERATION", "fake-embedding-v1"),
            ("OCR_EXTRACTION", None),
        ]

    command.downgrade(alembic_config, "b7397248a96b")
    engine.dispose()


def test_add_update_time_to_schedule_task_group_migration(
    tmp_path: Path, alembic_config: Config
) -> None:
    """Verify migration e7f8a9b0c1d2 adds update_time and backfills it from create_time."""
    db_path = tmp_path / "group_update_time.db"
    shutil.copy(Path("tests/fixtures/db_v1.sqlite").absolute(), db_path)
    url = f"sqlite:///{db_path}"
    alembic_config.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_config, "d4e5f6a7b8c9")

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO t_schedule_task_group (task_list_id, user_id, title, create_time) "
                "VALUES ('grp-1', 1, 'Work', 1700000012345)"
            )
        )

    command.upgrade(alembic_config, "e7f8a9b0c1d2")

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT create_time, update_time FROM t_schedule_task_group "
                "WHERE task_list_id = 'grp-1' AND user_id = 1"
            )
        ).fetchone()
        assert row is not None
        assert tuple(row) == (1700000012345, 1700000012345)

    command.downgrade(alembic_config, "d4e5f6a7b8c9")
    engine.dispose()


def test_make_schedule_task_list_id_nullable_migration(
    tmp_path: Path, alembic_config: Config
) -> None:
    """Verify migration f1a2b3c4d5e6 converts '' and '0' task_list_id values to NULL."""
    db_path = tmp_path / "task_list_id_nullable.db"
    shutil.copy(Path("tests/fixtures/db_v1.sqlite").absolute(), db_path)
    url = f"sqlite:///{db_path}"
    alembic_config.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_config, "e7f8a9b0c1d2")

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO t_schedule_task "
                "(task_id, task_list_id, user_id, title, status, is_reminder_on, create_time, update_time) "
                "VALUES "
                "('t1', '0', 1, 'Legacy Inbox', 'needsAction', 0, 1000, 1000), "
                "('t2', '', 1, 'Empty Inbox', 'needsAction', 0, 1000, 1000), "
                "('t3', 'grp-1', 1, 'Grouped', 'needsAction', 0, 1000, 1000)"
            )
        )

    command.upgrade(alembic_config, "f1a2b3c4d5e6")

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT task_id, task_list_id FROM t_schedule_task "
                "WHERE user_id = 1 ORDER BY task_id"
            )
        ).fetchall()
        assert [tuple(r) for r in rows] == [
            ("t1", None),
            ("t2", None),
            ("t3", "grp-1"),
        ]

    command.downgrade(alembic_config, "e7f8a9b0c1d2")
    with engine.connect() as conn:
        rows_down = conn.execute(
            text(
                "SELECT task_id, task_list_id FROM t_schedule_task "
                "WHERE user_id = 1 ORDER BY task_id"
            )
        ).fetchall()
        assert [tuple(r) for r in rows_down] == [
            ("t1", "0"),
            ("t2", "0"),
            ("t3", "grp-1"),
        ]

    engine.dispose()


def test_scope_summary_unique_identifier_by_user_migration(
    tmp_path: Path, alembic_config: Config
) -> None:
    """Verify migration a2b3c4d5e6f7 scopes f_summary and f_summary_tag unique_identifier and primary key by user_id."""
    db_path = tmp_path / "summary_user_scope.db"
    shutil.copy(Path("tests/fixtures/db_v1.sqlite").absolute(), db_path)
    url = f"sqlite:///{db_path}"
    alembic_config.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_config, "a2b3c4d5e6f7")

    engine = create_engine(url)
    with engine.begin() as conn:
        # Two different users can insert rows with the same id and unique_identifier
        conn.execute(
            text(
                "INSERT INTO f_summary "
                "(id, user_id, unique_identifier, is_summary_group, is_deleted, create_time, update_time) "
                "VALUES "
                "(500, 1, 'shared-uuid', 0, 0, 1000, 1000), "
                "(500, 2, 'shared-uuid', 0, 0, 1000, 1000)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO f_summary_tag "
                "(id, user_id, name, unique_identifier, create_time) "
                "VALUES "
                "(600, 1, 'Work', 'shared-tag-uuid', 1000), "
                "(600, 2, 'Work', 'shared-tag-uuid', 1000)"
            )
        )

    with engine.connect() as conn:
        summary_count = conn.execute(
            text(
                "SELECT count(*) FROM f_summary WHERE unique_identifier = 'shared-uuid'"
            )
        ).scalar()
        assert summary_count == 2

        tag_count = conn.execute(
            text(
                "SELECT count(*) FROM f_summary_tag WHERE unique_identifier = 'shared-tag-uuid'"
            )
        ).scalar()
        assert tag_count == 2

    # Clean up user 2's colliding rows before testing downgrade to global uniqueness
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM f_summary WHERE user_id = 2"))
        conn.execute(text("DELETE FROM f_summary_tag WHERE user_id = 2"))

    command.downgrade(alembic_config, "f1a2b3c4d5e6")
    engine.dispose()
