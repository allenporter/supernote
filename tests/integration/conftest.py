"""Pytest fixtures for out-of-process integration tests."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from supernote.testing.server_runner import ServerHandle, ServerRunner


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
    async with ServerRunner(
        storage_dir=tmp_path / "populated_server_data",
        initial_db=populated_fixture,
    ) as server_handle:
        yield server_handle
