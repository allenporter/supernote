"""Pytest fixtures for out-of-process integration tests."""

import hashlib
import shutil
from collections.abc import AsyncGenerator
from pathlib import Path

import aiohttp
import pytest

from supernote.client import Supernote
from supernote.testing.server_runner import ServerHandle, ServerRunner


async def generate_populated_v1_db_with_server(target_path: Path) -> Path:
    """Generate db_v1_populated.sqlite using an actual running server instance and SDK clients."""
    if target_path.exists():
        return target_path

    v1_fixture = Path("tests/fixtures/db_v1.sqlite").absolute()
    temp_dir = target_path.parent / "temp_seed_server"

    async with ServerRunner(storage_dir=temp_dir, initial_db=v1_fixture) as server:
        async with aiohttp.ClientSession() as session:
            admin_client = server.create_admin_client(session)
            password_md5 = hashlib.md5("seedpassword123".encode()).hexdigest()
            await admin_client.register(
                "seed_user@example.com", password_md5, "Seed User"
            )

        async with await Supernote.login(
            "seed_user@example.com", "seedpassword123", host=server.base_url
        ) as sn:
            # Create a folder via actual client API
            await sn.device.create_folder("/My Notes", equipment_no="WEB")

    # Copy the server-generated SQLite database to target_path
    generated_db = temp_dir / "system" / "supernote.db"
    shutil.copy(generated_db, target_path)
    shutil.rmtree(temp_dir, ignore_errors=True)
    return target_path


@pytest.fixture
async def live_server(tmp_path: Path) -> AsyncGenerator[ServerHandle, None]:
    """Provide a running out-of-process Supernote server with a fresh database."""
    async with ServerRunner(storage_dir=tmp_path / "server_data") as server_handle:
        yield server_handle


@pytest.fixture
async def migrated_live_server(tmp_path: Path) -> AsyncGenerator[ServerHandle, None]:
    """Provide a running server instance initialized with the v1 golden DB fixture."""
    v1_fixture = Path("tests/fixtures/db_v1.sqlite").absolute()
    async with ServerRunner(
        storage_dir=tmp_path / "migrated_server_data",
        initial_db=v1_fixture,
    ) as server_handle:
        yield server_handle


@pytest.fixture
async def populated_migrated_live_server(
    tmp_path: Path,
) -> AsyncGenerator[ServerHandle, None]:
    """Provide a running server initialized with a populated v1 DB containing a pre-existing user."""
    populated_fixture = Path("tests/fixtures/db_v1_populated.sqlite").absolute()
    await generate_populated_v1_db_with_server(populated_fixture)

    async with ServerRunner(
        storage_dir=tmp_path / "populated_server_data",
        initial_db=populated_fixture,
    ) as server_handle:
        yield server_handle
