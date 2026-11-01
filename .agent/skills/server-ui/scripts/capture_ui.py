#!/usr/bin/env python3
"""Spin up an ephemeral Supernote server, seed sample data, and capture a Playwright UI screenshot."""

import argparse
import asyncio
import socket
import sys
import tempfile
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from aiohttp import ClientSession, web
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from supernote.cli.client import async_cloud_seed  # noqa: E402
from supernote.client.auth import ConstantAuth  # noqa: E402
from supernote.client.client import Client  # noqa: E402
from supernote.client.login_client import LoginClient  # noqa: E402
from supernote.client.web import WebClient  # noqa: E402
from supernote.server.app import bootstrap_ephemeral_user, create_app  # noqa: E402
from supernote.server.config import AuthConfig, ServerConfig  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class EphemeralUiSession:
    """Running ephemeral server + authenticated WebClient and directory IDs."""

    base_url: str
    token: str
    web_client: WebClient
    note_dir_id: int
    document_dir_id: int

    async def new_authenticated_context(
        self,
        browser: Browser,
        width: int = 1360,
        height: int = 860,
        scale: int = 2,
    ) -> BrowserContext:
        """Create a browser context with supernote_token pre-injected before module load."""
        context = await browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=scale,
        )
        await context.add_init_script(
            f"localStorage.setItem('supernote_token', {self.token!r});"
        )
        return context


@asynccontextmanager
async def ephemeral_ui_session(
    seed: str = "notes",
) -> AsyncGenerator[EphemeralUiSession]:
    """Start an isolated ephemeral server and yield an authenticated session."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        http_port = _free_port()
        mcp_port = _free_port()
        cfg = ServerConfig(
            host="127.0.0.1",
            port=http_port,
            storage_dir=str(tmp / "storage"),
            mcp_port=mcp_port,
            _mcp_base_url=f"http://127.0.0.1:{mcp_port}",
            web_enabled=True,
            web_notebook_preview=True,
            auth=AuthConfig(
                enable_registration=True,
                secret_key="ephemeral-ui-preview-secret-key-32b!",
            ),
        )
        app = create_app(cfg)
        runner = web.AppRunner(app)
        await runner.setup()
        await bootstrap_ephemeral_user(app)
        site = web.TCPSite(runner, "127.0.0.1", http_port)
        await site.start()
        base_url = f"http://127.0.0.1:{http_port}"

        try:
            if seed == "full":
                await async_cloud_seed(url=base_url)

            async with ClientSession() as http:
                token = await LoginClient(Client(http, host=base_url)).login(
                    "debug@example.com", "password"
                )
                web_client = WebClient(
                    Client(http, auth=ConstantAuth(token), host=base_url)
                )
                root_list = await web_client.list_query(0)
                dirs_by_name = {
                    item.file_name: int(item.id)
                    for item in root_list.user_file_vo_list
                    if item.is_folder == "Y"
                }
                note_dir_id = dirs_by_name["Note"]
                document_dir_id = dirs_by_name["Document"]

                if seed in ("notes", "full"):
                    for name, rel_path in [
                        (
                            "Stroller_Design.note",
                            "tests/testdata/mmujynya/stroller.note",
                        ),
                        ("Numbered_1to10.note", "tests/testdata/philips/1to10.note"),
                    ]:
                        fixture_path = REPO_ROOT / rel_path
                        if fixture_path.exists():
                            await web_client.upload_file(
                                note_dir_id, name, fixture_path.read_bytes()
                            )

                yield EphemeralUiSession(
                    base_url=base_url,
                    token=token,
                    web_client=web_client,
                    note_dir_id=note_dir_id,
                    document_dir_id=document_dir_id,
                )
        finally:
            await runner.cleanup()


def _parse_viewport(value: str) -> tuple[int, int]:
    width_str, height_str = value.lower().split("x", maxsplit=1)
    return int(width_str), int(height_str)


async def _run_cli(args: argparse.Namespace) -> None:
    width, height = _parse_viewport(args.viewport)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    async with ephemeral_ui_session(seed=args.seed) as session:
        route = args.route.format(
            note_dir_id=session.note_dir_id,
            document_dir_id=session.document_dir_id,
        )
        if not route.startswith("/"):
            route = f"/{route}"

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            context = await session.new_authenticated_context(
                browser, width=width, height=height
            )
            page: Page = await context.new_page()
            await page.goto(f"{session.base_url}{route}", wait_until="networkidle")

            for selector in args.click:
                await page.locator(selector).first.click()
                await page.wait_for_load_state("networkidle")

            if args.wait_for:
                await page.locator(args.wait_for).first.wait_for(state="visible")

            if args.wait_ms > 0:
                await page.wait_for_timeout(args.wait_ms)

            await page.screenshot(path=str(output_path), full_page=args.full_page)
            await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Output PNG path.")
    parser.add_argument(
        "--route",
        default="/#/files/{note_dir_id}",
        help="Target route (supports {note_dir_id} and {document_dir_id}).",
    )
    parser.add_argument(
        "--seed",
        choices=("none", "notes", "full"),
        default="notes",
        help="Seed preset: 'notes' uploads sample .note files; 'full' also runs async_cloud_seed.",
    )
    parser.add_argument(
        "--click",
        action="append",
        default=[],
        help="Playwright selector to click after navigation (repeatable).",
    )
    parser.add_argument(
        "--wait-for",
        default=None,
        help="Playwright selector to wait for visibility before screenshot.",
    )
    parser.add_argument(
        "--wait-ms",
        type=int,
        default=800,
        help="Extra settle delay in ms before capturing screenshot.",
    )
    parser.add_argument(
        "--viewport",
        default="1360x860",
        help="Viewport dimensions as WIDTHxHEIGHT (rendered at 2x scale).",
    )
    parser.add_argument(
        "--full-page",
        action="store_true",
        help="Capture full scrollable page.",
    )
    asyncio.run(_run_cli(parser.parse_args()))


if __name__ == "__main__":
    main()
