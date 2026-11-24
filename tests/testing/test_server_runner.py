"""Tests for ServerRunner port allocation and bind-collision retries."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from supernote.testing.server_runner import (
    DEFAULT_PORT_BIND_RETRIES,
    ServerHandle,
    ServerRunner,
    find_free_ports,
)


def _make_fake_proc(
    returncode: int | None,
    stdout: bytes = b"",
    stderr: bytes = b"",
) -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    return proc


def test_find_free_ports_returns_distinct_ports() -> None:
    """Simultaneous port allocation returns distinct positive port numbers."""
    ports = find_free_ports(5)
    assert len(ports) == 5
    assert len(set(ports)) == 5
    assert all(p > 0 for p in ports)
    assert find_free_ports(0) == []


async def test_server_runner_retries_on_address_in_use(tmp_path: Path) -> None:
    """Auto-allocated ports are re-picked and retried when a bind collision occurs."""
    failed_proc = _make_fake_proc(
        returncode=3,
        stderr=b"ERROR: [Errno 98] error while attempting to bind on address ('127.0.0.1', 45967): [errno 98] address already in use\n",
    )
    healthy_proc = _make_fake_proc(returncode=None)

    spawned_envs: list[dict[str, str]] = []

    async def fake_create_subprocess_exec(*_args: Any, **kwargs: Any) -> MagicMock:
        spawned_envs.append(dict(kwargs["env"]))
        return failed_proc if len(spawned_envs) == 1 else healthy_proc

    with (
        patch(
            "supernote.testing.server_runner.find_free_ports",
            side_effect=[[40001, 45967], [40002, 45968]],
        ),
        patch(
            "supernote.testing.server_runner.asyncio.create_subprocess_exec",
            side_effect=fake_create_subprocess_exec,
        ),
        patch.object(ServerHandle, "is_healthy", new=AsyncMock(return_value=True)),
    ):
        runner = ServerRunner(storage_dir=tmp_path / "server_data")
        handle = await runner.start()

    assert len(spawned_envs) == 2
    assert spawned_envs[0]["SUPERNOTE_PORT"] == "40001"
    assert spawned_envs[0]["SUPERNOTE_MCP_PORT"] == "45967"
    assert spawned_envs[1]["SUPERNOTE_PORT"] == "40002"
    assert spawned_envs[1]["SUPERNOTE_MCP_PORT"] == "45968"
    assert runner.port == 40002
    assert runner.mcp_port == 45968
    assert handle.port == 40002
    assert handle.mcp_port == 45968
    assert handle.base_url == "http://127.0.0.1:40002"


async def test_server_runner_does_not_retry_explicit_ports(tmp_path: Path) -> None:
    """Explicitly requested ports fail immediately without retrying."""
    failed_proc = _make_fake_proc(
        returncode=3,
        stderr=b"ERROR: [Errno 98] address already in use\n",
    )
    create_exec = AsyncMock(return_value=failed_proc)

    with patch(
        "supernote.testing.server_runner.asyncio.create_subprocess_exec",
        new=create_exec,
    ):
        runner = ServerRunner(
            storage_dir=tmp_path / "server_data",
            port=41001,
            mcp_port=41002,
        )
        with pytest.raises(RuntimeError, match="address already in use"):
            await runner.start()

    assert create_exec.await_count == 1


async def test_server_runner_does_not_retry_non_bind_errors(tmp_path: Path) -> None:
    """Non-port-collision startup failures surface immediately without retrying."""
    failed_proc = _make_fake_proc(
        returncode=1,
        stderr=b"Traceback: database migration failed\n",
    )
    create_exec = AsyncMock(return_value=failed_proc)

    with patch(
        "supernote.testing.server_runner.asyncio.create_subprocess_exec",
        new=create_exec,
    ):
        runner = ServerRunner(storage_dir=tmp_path / "server_data")
        with pytest.raises(RuntimeError, match="database migration failed"):
            await runner.start()

    assert create_exec.await_count == 1


async def test_server_runner_exhausts_port_bind_retries(tmp_path: Path) -> None:
    """Repeated bind collisions raise RuntimeError after exhausting retries."""
    create_exec = AsyncMock(
        side_effect=lambda *_a, **_kw: _make_fake_proc(
            returncode=3,
            stderr=b"ERROR: [Errno 98] address already in use\n",
        )
    )

    with patch(
        "supernote.testing.server_runner.asyncio.create_subprocess_exec",
        new=create_exec,
    ):
        runner = ServerRunner(storage_dir=tmp_path / "server_data")
        with pytest.raises(RuntimeError, match="address already in use"):
            await runner.start()

    assert create_exec.await_count == DEFAULT_PORT_BIND_RETRIES
