"""Integration test verifying backward compatibility and self-healing for v0.20.0 schedule database snapshot via REST API."""

import shutil
from pathlib import Path

import jwt
from aiohttp.test_utils import TestClient, TestServer

from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.schedule import ScheduleClient
from supernote.server.app import create_app
from supernote.server.config import AuthConfig, ServerConfig
from supernote.server.db.migrations import run_migrations
from supernote.server.services.user import JWT_ALGORITHM

FIXTURES_DIR = Path(__file__).parent.parent.parent.parent / "fixtures"
SCHEDULE_V20_FIXTURE_PATH = FIXTURES_DIR / "db_v0_20_0_schedule.sqlite"


async def test_load_v0_20_0_schedule_database_via_api(tmp_path: Path) -> None:
    """Verify that a v0.20.0 schedule database with orphaned revision c9a8b7c6d5e4 heals and serves data correctly via REST API."""
    storage_dir = tmp_path / "storage"
    db_file = storage_dir / "system" / "supernote.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCHEDULE_V20_FIXTURE_PATH, db_file)

    # Run migrations on the copied database to head (triggers self-healing)
    sync_url = f"sqlite:///{db_file}"
    run_migrations(sync_url, "head")

    config = ServerConfig(
        storage_dir=str(storage_dir),
        auth=AuthConfig(secret_key="test-secret-key-32-characters-long!!"),
        mcp_port=0,
    )
    app = create_app(config)

    server = TestServer(app)
    await server.start_server()

    # Generate auth token for the test user
    test_user = "test@example.com"
    secret = config.auth.secret_key
    token = jwt.encode({"sub": test_user}, secret, algorithm=JWT_ALGORITHM)
    await app["coordination_service"].set_value(
        f"session:{token}", f"{test_user}|", ttl=3600
    )

    class TokenAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            return token

    client = TestClient(server)
    await client.start_server()
    base_url = str(client.make_url(""))

    supernote_client = Client(client.session, auth=TokenAuth(), host=base_url)
    schedule_client = ScheduleClient(supernote_client)

    try:
        # List Task Groups via API
        groups = [g async for g in schedule_client.list_groups()]
        assert len(groups) >= 1
        inbox_group = next((g for g in groups if g.title == "Inbox Tasks"), None)
        assert inbox_group is not None
        assert inbox_group.task_list_id == "744362741145272573"
        group_id = inbox_group.task_list_id

        # List Tasks in Group via API
        tasks_vo = await schedule_client.get_tasks_all(group_id=group_id)
        assert tasks_vo.success is True
        tasks_by_title = {t.title: t for t in tasks_vo.schedule_task}
        assert "Buy Milk Before Upgrade" in tasks_by_title
        assert "Schedule Dentist Appointment" in tasks_by_title
        assert "Task Created in v0.20.0" in tasks_by_title

        # Assert exact task IDs to verify stability across schema upgrades
        milk_task = tasks_by_title["Buy Milk Before Upgrade"]
        assert milk_task.task_id == "744362741170438528"
        assert milk_task.task_list_id == "744362741145272573"
        assert milk_task.detail == "Must purchase whole milk"

        dentist_task = tasks_by_title["Schedule Dentist Appointment"]
        assert dentist_task.task_id == "744362741199799018"
        assert dentist_task.task_list_id == "744362741145272573"
        assert dentist_task.detail == "Routine checkup"

        v20_task = tasks_by_title["Task Created in v0.20.0"]
        assert v20_task.task_id == "744362741200000001"
        assert v20_task.task_list_id == "744362741145272573"
        assert v20_task.detail == "Created under string UUID schema"

        # Retrieve Individual Task by ID via API
        assert v20_task.task_id is not None
        v20_detail = await schedule_client.get_task(v20_task.task_id)
        assert v20_detail.success is True
        assert v20_detail.task_id == "744362741200000001"
        assert v20_detail.title == "Task Created in v0.20.0"

    finally:
        await client.close()
        await server.close()
