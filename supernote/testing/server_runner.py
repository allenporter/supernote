"""Out-of-process live server runner for integration testing and CLI debugging.

Example:
    from pathlib import Path
    import aiohttp
    from supernote.testing import ServerRunner

    # Run a fresh server instance asynchronously in a temporary directory
    async with ServerRunner(storage_dir=Path("/tmp/my_server")) as server:
        print(f"Server running at: {server.base_url}")
        print(
            f"CLI command string: {server.get_login_cmd_str('admin@example.com', 'secret')}"
        )

        # Interact with the server via admin client
        async with aiohttp.ClientSession() as session:
            admin_client = server.create_admin_client(session)
            await admin_client.register("admin@example.com", "secret")

        # Or execute CLI commands against it asynchronously
        result = await server.run_cli(
            "cloud",
            "login",
            "admin@example.com",
            "--password",
            "secret",
            "--url",
            server.base_url,
        )
        print(result.stdout)
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import aiohttp

from supernote.client.admin import AdminClient
from supernote.client.auth import ConstantAuth
from supernote.client.client import Client

DEFAULT_HOST = "127.0.0.1"
DEFAULT_HEALTH_CHECK_TIMEOUT = 15.0
DEFAULT_HEALTH_CHECK_INTERVAL = 0.1
DEFAULT_PROCESS_STOP_TIMEOUT = 5.0


def find_free_port(host: str = DEFAULT_HOST) -> int:
    """Find an available TCP port on the host interface."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


@dataclass
class ServerHandle:
    """Handle to a running server process."""

    host: str
    port: int
    mcp_port: int
    base_url: str
    proc: asyncio.subprocess.Process
    storage_dir: Path
    db_path: Path
    env: dict[str, str]

    async def is_healthy(self, timeout: float = 1.0) -> bool:
        """Check if the server healthcheck endpoint responds with HTTP 200."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/health",
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def stop(self, timeout: float = DEFAULT_PROCESS_STOP_TIMEOUT) -> None:
        """Terminate the server process cleanly and wait for it to exit."""
        if self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()

    def create_client(
        self,
        session: aiohttp.ClientSession,
        access_token: str | None = None,
    ) -> Client:
        """Create a Python SDK Client targeting this running server instance."""
        auth = ConstantAuth(access_token) if access_token else None
        return Client(session, host=self.base_url, auth=auth)

    def create_admin_client(
        self,
        session: aiohttp.ClientSession,
        access_token: str | None = None,
    ) -> AdminClient:
        """Create an AdminClient targeting this running server instance."""
        return AdminClient(self.create_client(session, access_token=access_token))

    def get_login_cmd_str(self, email: str, password: str) -> str:
        """Return the formatted CLI shell command string for logging into this server instance.

        Args:
            email: Account email address to log in with.
            password: Account password to log in with.

        Returns:
            Formatted CLI command string (e.g. `supernote cloud login email --password password --url base_url`).
        """
        return (
            f"supernote cloud login {email} --password {password} --url {self.base_url}"
        )

    async def run_cli(
        self,
        *args: str,
        env: dict[str, str] | None = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Execute the `supernote` CLI tool in a subprocess targeting this server.

        Args:
            *args: Command line arguments to pass to the `supernote` CLI tool.
            env: Optional environment variable overrides for the CLI process.
            check: If True, raises RuntimeError if the CLI process exits with non-zero exit code.

        Returns:
            A subprocess.CompletedProcess containing returncode, stdout, and stderr string outputs.
        """
        merged_env = dict(self.env)
        if env:
            merged_env.update(env)

        cmd = [sys.executable, "-m", "supernote.cli.main", *args]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=merged_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        returncode = proc.returncode if proc.returncode is not None else 1

        if check and returncode != 0:
            raise RuntimeError(
                f"CLI command failed with exit code {returncode}.\n"
                f"Command: {' '.join(cmd)}\n"
                f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
            )

        return subprocess.CompletedProcess(
            args=cmd,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )


class ServerRunner:
    """Async context manager and launcher for out-of-process Supernote servers."""

    def __init__(
        self,
        storage_dir: Path,
        initial_db: Path | None = None,
        port: int | None = None,
        mcp_port: int | None = None,
        host: str = DEFAULT_HOST,
        env: dict[str, str] | None = None,
        health_check_timeout: float = DEFAULT_HEALTH_CHECK_TIMEOUT,
    ) -> None:
        """Initialize the server runner.

        Args:
            storage_dir: Path to root directory where server system files, storage blobs,
                and SQLite databases will be stored.
            initial_db: Optional path to an existing SQLite database file (e.g. `db_v1.sqlite`).
                If provided, it is copied to `<storage_dir>/system/supernote.db` prior to
                server startup so Alembic database migrations and legacy data compatibility
                can be tested.
            port: TCP port for the server to listen on. If None, an available port is automatically
                selected on the host interface.
            mcp_port: TCP port for the MCP server to listen on. If None, an available port is automatically
                selected on the host interface.
            host: Network interface host to bind to (default: "127.0.0.1").
            env: Optional environment variable overrides for the server process.
            health_check_timeout: Maximum time in seconds to wait for `/api/health` to respond
                HTTP 200 before timing out.
        """
        self.storage_dir = storage_dir.resolve()
        self.initial_db = initial_db.resolve() if initial_db else None
        self.host = host
        self.port = port if port is not None else find_free_port(self.host)
        self.mcp_port = mcp_port if mcp_port is not None else find_free_port(self.host)
        self.health_check_timeout = health_check_timeout
        self.custom_env = env or {}
        self.handle: ServerHandle | None = None

    async def start(self) -> ServerHandle:
        """Start the server process asynchronously and wait until healthcheck passes."""
        system_dir = self.storage_dir / "system"
        system_dir.mkdir(parents=True, exist_ok=True)
        db_path = system_dir / "supernote.db"

        if self.initial_db:
            if not self.initial_db.exists():
                raise FileNotFoundError(f"Initial DB not found: {self.initial_db}")
            shutil.copy(self.initial_db, db_path)

        base_url = f"http://{self.host}:{self.port}"
        process_env = {
            **os.environ,
            "SUPERNOTE_HOST": self.host,
            "SUPERNOTE_PORT": str(self.port),
            "SUPERNOTE_MCP_PORT": str(self.mcp_port),
            "SUPERNOTE_STORAGE_DIR": str(self.storage_dir),
            "HOME": str(self.storage_dir),
            "XDG_CACHE_HOME": str(self.storage_dir / ".cache"),
            "XDG_CONFIG_HOME": str(self.storage_dir / ".config"),
            "PYTHONUNBUFFERED": "1",
            **self.custom_env,
        }

        cmd = [sys.executable, "-m", "supernote.cli.server", "serve"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=process_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        handle = ServerHandle(
            host=self.host,
            port=self.port,
            mcp_port=self.mcp_port,
            base_url=base_url,
            proc=proc,
            storage_dir=self.storage_dir,
            db_path=db_path,
            env=process_env,
        )

        # Poll health check endpoint until server is ready
        start_time = asyncio.get_running_loop().time()
        while (
            asyncio.get_running_loop().time() - start_time < self.health_check_timeout
        ):
            if proc.returncode is not None:
                stdout_bytes, stderr_bytes = await proc.communicate()
                stdout = stdout_bytes.decode("utf-8", errors="replace")
                stderr = stderr_bytes.decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"Server process terminated unexpectedly with code {proc.returncode}.\n"
                    f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                )

            if await handle.is_healthy():
                self.handle = handle
                return handle

            await asyncio.sleep(DEFAULT_HEALTH_CHECK_INTERVAL)

        # Timeout reached
        proc.terminate()
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=2.0
            )
        except asyncio.TimeoutError:
            proc.kill()
            stdout_bytes, stderr_bytes = await proc.communicate()

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        raise TimeoutError(
            f"Server failed to become healthy within {self.health_check_timeout}s.\n"
            f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        )

    async def stop(self) -> None:
        """Stop the running server process if active."""
        if self.handle:
            await self.handle.stop()
            self.handle = None

    async def __aenter__(self) -> ServerHandle:
        return await self.start()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()
