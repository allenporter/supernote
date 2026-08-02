"""End-to-end integration tests using out-of-process live server runner."""

import hashlib

import aiohttp
import pytest

from supernote.client import Supernote
from supernote.testing.server_runner import ServerHandle

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_fresh_live_server_health_and_admin_user_registration(
    live_server: ServerHandle,
) -> None:
    """Verify fresh live server starts, healthcheck passes, and user registration works."""
    assert await live_server.is_healthy()

    user_email = "testuser@example.com"
    user_password = "password123"
    password_md5 = hashlib.md5(user_password.encode("utf-8")).hexdigest()

    # Register user via Admin API
    async with aiohttp.ClientSession() as session:
        admin_client = live_server.create_admin_client(session)
        await admin_client.register(user_email, password_md5, "Test User")

    # Verify user can log in via Supernote SDK
    async with await Supernote.login(
        user_email, user_password, host=live_server.base_url
    ) as sn:
        assert sn.token is not None
        # List root directory over live HTTP socket
        files = await sn.device.list_folder("/")
        assert files is not None


@pytest.mark.asyncio
async def test_migrated_db_live_server(
    migrated_live_server: ServerHandle,
) -> None:
    """Verify live server starts with v1 database, migrates to head, and serves requests."""
    assert await migrated_live_server.is_healthy()
    assert migrated_live_server.db_path.exists()

    user_email = "migrated_user@example.com"
    user_password = "password123"
    password_md5 = hashlib.md5(user_password.encode("utf-8")).hexdigest()

    # Create admin client pointing to the migrated server instance
    async with aiohttp.ClientSession() as session:
        admin_client = migrated_live_server.create_admin_client(session)
        await admin_client.register(user_email, password_md5, "Migrated User")

    # Verify login works against the migrated database
    async with await Supernote.login(
        user_email, user_password, host=migrated_live_server.base_url
    ) as sn:
        assert sn.token is not None


@pytest.mark.asyncio
async def test_populated_migrated_db_user_login(
    populated_migrated_live_server: ServerHandle,
) -> None:
    """Verify pre-existing v1 user can log in and access server endpoints after migration."""
    assert await populated_migrated_live_server.is_healthy()

    # Pre-seeded user credentials in v1 database
    user_email = "seed_user@example.com"
    user_password = "seedpassword123"

    # Attempt login without registering (verifying pre-existing account works after migration)
    async with await Supernote.login(
        user_email, user_password, host=populated_migrated_live_server.base_url
    ) as sn:
        assert sn.token is not None
        files = await sn.device.list_folder("/")
        assert files is not None


@pytest.mark.asyncio
async def test_cli_provisioning_and_login(live_server: ServerHandle) -> None:
    """Verify user provisioning and CLI login/commands in a subprocess."""
    assert await live_server.is_healthy()

    cli_email = "cliuser@example.com"
    cli_password = "clipassword123"
    password_md5 = hashlib.md5(cli_password.encode("utf-8")).hexdigest()

    # Provision user via admin API
    async with aiohttp.ClientSession() as session:
        admin_client = live_server.create_admin_client(session)
        await admin_client.register(cli_email, password_md5, "CLI User")

    # Execute `supernote cloud login` CLI command via async subprocess
    login_result = await live_server.run_cli(
        "cloud",
        "login",
        cli_email,
        "--password",
        cli_password,
        "--url",
        live_server.base_url,
    )
    assert login_result.returncode == 0, f"Login failed: {login_result.stderr}"
    assert "Login successful" in login_result.stdout

    # Execute `supernote cloud ls` CLI command using cached credentials
    ls_result = await live_server.run_cli("cloud", "ls")
    assert ls_result.returncode == 0, f"ls failed: {ls_result.stderr}"
