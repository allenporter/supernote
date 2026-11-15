"""End-to-end headless Playwright smoke tests for the Supernote Cloud Web UI.

Automatically skipped when Playwright (or its Chromium browser binary) is not
installed in minimal Python environments, and executed in CI via
`.github/workflows/frontend.yaml`.
"""

from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.client import Client
from supernote.client.schedule import ScheduleClient
from supernote.client.web import WebClient

SAMPLE_UI_NOTE = Path(__file__).resolve().parents[1] / "testdata/philips/1to10.note"


async def test_web_ui_desktop_and_mobile_smoke(
    client: TestClient,
    authenticated_client: Client,
    web_client: WebClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify core desktop and mobile Web UI flows with zero runtime errors."""
    playwright_async = pytest.importorskip("playwright.async_api")
    errors: list[str] = []

    def attach_listeners(page: Any) -> None:
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
        page.on(
            "console",
            lambda msg: (
                errors.append(f"console.error: {msg.text}")
                if msg.type == "error" and "status of 404" not in msg.text
                else None
            ),
        )
        page.on(
            "response",
            lambda resp: (
                errors.append(f"HTTP {resp.status}: {resp.url}")
                if resp.status >= 400
                and not (
                    resp.status == 404 and resp.url.endswith("/api/extended/transcript")
                )
                else None
            ),
        )

    base_url = str(client.make_url("")).rstrip("/")
    token = auth_headers["x-access-token"]

    root_list = await web_client.list_query(0)
    note_dir_id = next(
        int(item.id)
        for item in root_list.user_file_vo_list
        if item.is_folder == "Y" and item.file_name == "Note"
    )
    await web_client.upload_file(
        note_dir_id, "Numbered_1to10.note", SAMPLE_UI_NOTE.read_bytes()
    )
    schedule_client = ScheduleClient(authenticated_client)
    group = await schedule_client.create_group("Inbox Tasks")
    await schedule_client.create_task(
        group_id=group.task_list_id,
        title="Seeded Smoke Task",
        importance="high",
    )

    async with playwright_async.async_playwright() as p:
        try:
            browser = await p.chromium.launch()
        except playwright_async.Error as exc:
            pytest.skip(f"Chromium browser binary not installed: {exc}")

        try:
            # 1. Desktop E2E flow (1360x860)
            desktop = await browser.new_context(viewport={"width": 1360, "height": 860})
            await desktop.add_init_script(
                f"localStorage.setItem('supernote_token', {token!r});"
            )
            page = await desktop.new_page()
            attach_listeners(page)

            await page.goto(
                f"{base_url}/#/files/{note_dir_id}", wait_until="networkidle"
            )
            await page.get_by_role("button", name="List view").click()
            await page.get_by_role("button", name="Grid view").click()

            # Open .note viewer, step page, toggle tabs
            await page.get_by_text("Numbered_1to10.note").first.click()
            await page.locator('[data-page-index="0"] img').wait_for(
                state="visible", timeout=15000
            )
            await page.get_by_role("button", name="Next page").first.click()
            await page.wait_for_timeout(200)
            assert "page=2" in page.url

            await page.get_by_role("button", name="Summaries").click()
            await page.get_by_text("Notebook Summaries").wait_for(state="visible")
            await page.get_by_role("button", name="Back to files").click()

            # Tasks & Schedule view + ICS modal
            await page.get_by_role("button", name="Tasks").click()
            await page.get_by_text("Seeded Smoke Task").first.wait_for(state="visible")
            await page.get_by_role("button", name="Export .ics Feed").click()
            ics_textarea = page.get_by_role(
                "dialog", name="Export iCalendar Feed"
            ).locator("textarea")
            await ics_textarea.wait_for(state="visible")
            assert "BEGIN:VCALENDAR" in await ics_textarea.input_value()
            await page.keyboard.press("Escape")

            # System status panel & global search modal
            await page.get_by_role("button", name="System Status").click()
            assert page.url.endswith("#/system")
            await page.keyboard.press("Escape")

            await page.get_by_role("button", name="Global Search").click()
            await page.locator('input[placeholder*="Search"]').wait_for(state="visible")
            await page.keyboard.press("Escape")
            await desktop.close()

            # 2. Mobile responsive check (375x812)
            mobile = await browser.new_context(viewport={"width": 375, "height": 812})
            await mobile.add_init_script(
                f"localStorage.setItem('supernote_token', {token!r});"
            )
            mpage = await mobile.new_page()
            attach_listeners(mpage)

            await mpage.goto(
                f"{base_url}/#/files/{note_dir_id}", wait_until="networkidle"
            )
            await mpage.get_by_text("Numbered_1to10.note").first.wait_for(
                state="visible"
            )
            try:
                await mpage.wait_for_function(
                    "() => document.documentElement.scrollWidth <= window.innerWidth",
                    timeout=5000,
                )
            except playwright_async.TimeoutError:
                pass
            overflow = await mpage.evaluate(
                "document.documentElement.scrollWidth - window.innerWidth"
            )
            assert overflow <= 0, f"Mobile horizontal overflow: {overflow}px"

            await mpage.get_by_text("Numbered_1to10.note").first.click()
            await mpage.locator('[data-page-index="0"] img').wait_for(
                state="visible", timeout=15000
            )
            viewer_overflow = await mpage.evaluate(
                "document.documentElement.scrollWidth - window.innerWidth"
            )
            assert viewer_overflow <= 0, (
                f"Mobile viewer horizontal overflow: {viewer_overflow}px"
            )
            await mpage.get_by_role("button", name="Transcript", exact=True).click()
            await mpage.get_by_role("button", name="Hide Panel").wait_for(
                state="visible"
            )
            await mobile.close()
        finally:
            await browser.close()

    assert not errors, f"Unexpected browser/network errors: {errors}"
