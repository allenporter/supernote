"""End-to-end headless Playwright smoke tests for the Supernote Cloud Web UI.

Automatically skipped when Playwright (or its Chromium browser binary) is not
installed in minimal Python environments, and executed in CI via
`.github/workflows/frontend.yaml`.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient
from sqlalchemy import select

from supernote.client.client import Client
from supernote.client.schedule import ScheduleClient
from supernote.client.web import WebClient
from supernote.models.summary import AddSummaryDTO, AddSummaryGroupDTO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.keys import (
    PROCESSOR_SERVICE_KEY,
    SESSION_MANAGER_KEY,
    SUMMARY_SERVICE_KEY,
    USER_SERVICE_KEY,
)

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
    assert client.app is not None
    await asyncio.wait_for(client.app[PROCESSOR_SERVICE_KEY].queue.join(), timeout=15.0)

    note_list = await web_client.list_query(note_dir_id)
    uploaded_note = next(
        f for f in note_list.user_file_vo_list if f.file_name == "Numbered_1to10.note"
    )
    note_file_id = int(uploaded_note.id)

    page1_transcript = "Seeded Page 1 OCR Transcript\n- Verified copy button"
    async with client.app[SESSION_MANAGER_KEY].session() as db_session:
        page_rows = (
            (
                await db_session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == note_file_id)
                    .order_by(NotePageContentDO.page_index)
                )
            )
            .scalars()
            .all()
        )
        if page_rows:
            page_rows[0].text_content = page1_transcript
        else:
            db_session.add(
                NotePageContentDO(
                    file_id=note_file_id,
                    page_index=0,
                    page_id="P202606180001",
                    text_content=page1_transcript,
                )
            )
        await db_session.commit()

    user_email = (await web_client.query_user()).email
    assert user_email is not None
    summary_service = client.app[SUMMARY_SERVICE_KEY]
    await summary_service.add_group(
        user_email,
        AddSummaryGroupDTO(
            unique_identifier="smoke-note-group",
            name="Numbered_1to10.note",
            md5_hash="0123456789abcdef",
        ),
    )
    await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=note_file_id,
            unique_identifier="smoke-note-summary",
            parent_unique_identifier="smoke-note-group",
            content=(
                "## 2026-06-18 (Page 1)\n"
                "- **Decision**: Shipped Markdown summaries\n"
                "- [x] Verify [Spec](https://example.com/spec)\n\n"
                "<script>window.__xss = true;</script>"
            ),
            data_source="gemini-2.5-flash",
            source_path="/Note/Numbered_1to10.note",
        ),
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
            # Desktop E2E flow (1360x860)
            desktop = await browser.new_context(
                viewport={"width": 1360, "height": 860},
                permissions=["clipboard-read", "clipboard-write"],
            )
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

            # Verify Escape dismisses OS file-drag dropzone overlay
            await page.evaluate(
                """() => {
                    const dt = new DataTransfer();
                    dt.items.add(new File(['x'], 'demo.note'));
                    document.querySelector('main [class*="relative"]')?.dispatchEvent(
                        new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt })
                    );
                }"""
            )
            drop_banner = page.get_by_text("Drop files to upload")
            await drop_banner.wait_for(state="visible")
            await page.keyboard.press("Escape")
            await drop_banner.wait_for(state="hidden")

            # Open .note viewer, copy OCR page transcript, step page, verify Markdown summary
            await page.get_by_text("Numbered_1to10.note").first.click()
            await page.locator('[data-page-index="0"] img').wait_for(
                state="visible", timeout=15000
            )
            copy_btn = page.locator('[data-copy-page="0"]')
            await copy_btn.wait_for(state="visible")
            await copy_btn.click()
            await page.wait_for_function(
                """() => {
                    const el = document.querySelector('[data-copy-page="0"]');
                    return el && el.textContent.includes('Copied');
                }"""
            )
            assert (
                await page.evaluate("() => navigator.clipboard.readText()")
                == page1_transcript
            )

            await page.get_by_role("button", name="Next page").first.click()
            await page.wait_for_function(
                "() => window.location.hash.includes('page=2')"
            )
            assert "page=2" in page.url

            await page.get_by_role("button", name="Summaries").click()
            await page.get_by_text("Notebook Summaries").wait_for(state="visible")
            summary_prose = page.locator("[data-summary-card] .markdown-prose").first
            await summary_prose.wait_for(state="visible")
            md_checks = await summary_prose.evaluate(
                """(el) => ({
                    h2: el.querySelector('h2')?.textContent?.trim() || '',
                    hasCheckedTask: Boolean(el.querySelector('.md-task-box.is-checked')),
                    linkTarget: el.querySelector('a')?.getAttribute('target') || '',
                    linkRel: el.querySelector('a')?.getAttribute('rel') || '',
                    scriptCount: el.querySelectorAll('script').length,
                })"""
            )
            assert md_checks == {
                "h2": "2026-06-18 (Page 1)",
                "hasCheckedTask": True,
                "linkTarget": "_blank",
                "linkRel": "noopener noreferrer",
                "scriptCount": 0,
            }
            await page.get_by_role("button", name="Back to files").click()

            # Recycle Bin E2E: create folder -> soft-delete -> open #/recycle -> restore -> delete again -> empty
            await page.get_by_role("button", name="New Folder").click()
            await page.get_by_placeholder("Folder name").fill("RecycleSmokeFolder")
            await page.get_by_role("button", name="Create Folder").click()
            await page.get_by_text("RecycleSmokeFolder").first.wait_for(state="visible")

            await page.get_by_role("button", name="List view").click()
            folder_card = page.locator(
                ".file-card", has_text="RecycleSmokeFolder"
            ).first
            await folder_card.locator('input[type="checkbox"]').check()
            await page.get_by_role("button", name="Delete", exact=True).click()
            del_modal = page.get_by_role("dialog", name="Confirm Delete")
            await del_modal.wait_for(state="visible")
            await del_modal.get_by_role("button", name="Delete").click()
            await del_modal.wait_for(state="hidden")

            await page.get_by_role("button", name="Recycle Bin").click()
            await page.wait_for_function("() => location.hash === '#/recycle'")
            recycle_row = page.locator(".recycle-row", has_text="RecycleSmokeFolder")
            await recycle_row.wait_for(state="visible")
            await recycle_row.get_by_role("button", name="Restore").click()
            await page.get_by_text("Recycle Bin is empty").wait_for(state="visible")

            await page.get_by_role("button", name="Back to Files").click()
            await page.get_by_text("RecycleSmokeFolder").first.wait_for(state="visible")

            # Re-delete and empty Recycle Bin to verify destructive confirmation flow
            folder_card = page.locator(
                ".file-card", has_text="RecycleSmokeFolder"
            ).first
            await folder_card.locator('input[type="checkbox"]').check()
            await page.get_by_role("button", name="Delete", exact=True).click()
            await del_modal.get_by_role("button", name="Delete").click()
            await del_modal.wait_for(state="hidden")

            await page.get_by_role("button", name="Recycle Bin").click()
            await recycle_row.wait_for(state="visible")
            await page.get_by_role("button", name="Empty Recycle Bin").click()
            empty_modal = page.get_by_role("dialog", name="Confirm Empty Recycle Bin")
            await empty_modal.wait_for(state="visible")
            await empty_modal.get_by_role("button", name="Empty Recycle Bin").click()
            await empty_modal.wait_for(state="hidden")
            await page.get_by_text("Recycle Bin is empty").wait_for(state="visible")

            # Tasks & Schedule view + stacked Search over ICS modal LIFO Escape dismissal
            await page.get_by_role("button", name="Tasks").click()
            await page.get_by_text("Seeded Smoke Task").first.wait_for(state="visible")
            await page.get_by_role("button", name="Export .ics Feed").click()
            ics_dialog = page.get_by_role("dialog", name="Export iCalendar Feed")
            ics_textarea = ics_dialog.locator("textarea")
            await ics_textarea.wait_for(state="visible")
            assert "BEGIN:VCALENDAR" in await ics_textarea.input_value()

            await page.keyboard.press("Control+k")
            search_dialog = page.get_by_role("dialog", name="Global Search")
            await search_dialog.wait_for(state="visible")
            await page.keyboard.press("Escape")
            await search_dialog.wait_for(state="hidden")
            assert await ics_dialog.is_visible()
            await page.keyboard.press("Escape")
            await ics_dialog.wait_for(state="hidden")

            # System status panel & global search modal
            await page.get_by_role("button", name="System Status").click()
            assert page.url.endswith("#/system")
            await page.keyboard.press("Escape")

            await page.get_by_role("button", name="Global Search").click()
            await page.locator('input[placeholder*="Search"]').wait_for(state="visible")
            await page.keyboard.press("Escape")
            await desktop.close()

            # Mobile responsive check (375x812)
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
            await mpage.keyboard.press("Escape")
            await mpage.get_by_role("button", name="Transcript", exact=True).wait_for(
                state="visible"
            )
            await mobile.close()
        finally:
            await browser.close()

    assert not errors, f"Unexpected browser/network errors: {errors}"


async def test_web_ui_settings_manages_clients_and_api_keys(
    client: TestClient,
    auth_headers: dict[str, str],
    test_user_id: int,
) -> None:
    """Verify #/settings lists, creates, and revokes OAuth grants and API keys."""
    playwright_async = pytest.importorskip("playwright.async_api")
    assert client.app is not None
    user_service = client.app[USER_SERVICE_KEY]
    await user_service.create_oauth_grant(
        test_user_id, "https://client.example.com/", ["supernote:all"]
    )
    base_url = str(client.make_url("")).rstrip("/")
    token = auth_headers["x-access-token"]

    async with playwright_async.async_playwright() as p:
        try:
            browser = await p.chromium.launch()
        except playwright_async.Error as exc:
            pytest.skip(f"Chromium browser binary not installed: {exc}")
        try:
            context = await browser.new_context(viewport={"width": 1360, "height": 860})
            await context.add_init_script(
                f"localStorage.setItem('supernote_token', {token!r});"
            )
            page = await context.new_page()
            await page.goto(f"{base_url}/#/files", wait_until="networkidle")
            await page.get_by_role("button", name="Settings").click()
            assert page.url.endswith("#/settings")

            await page.get_by_text("client.example.com").wait_for(state="visible")
            await page.get_by_text("No API keys.").wait_for(state="visible")

            await page.get_by_label("API key name").fill("Laptop CLI")
            await page.get_by_role("button", name="Create key").click()
            created = page.get_by_role("status")
            await created.wait_for(state="visible")
            raw_key = (await created.locator("code").text_content() or "").strip()
            assert raw_key.startswith("sn_")
            user_keys = await user_service.list_api_keys(test_user_id)
            assert [k.name for k in user_keys] == ["Laptop CLI"]
            await page.get_by_role("button", name="Done").click()
            assert raw_key not in await page.content()

            await page.get_by_role("button", name="Revoke").click()
            dialog = page.get_by_role("dialog", name="Confirm Revoke")
            await dialog.get_by_role("button", name="Revoke").click()
            await page.get_by_text("No API keys.").wait_for(state="visible")
            assert await user_service.list_api_keys(test_user_id) == []

            await page.get_by_label("API key name").fill("Tablet")
            await page.get_by_role("button", name="Create key").click()
            await created.wait_for(state="visible")
            await page.get_by_role("button", name="Revoke").click()
            box = await dialog.bounding_box()
            assert box is not None and box["y"] == 0
            await dialog.get_by_role("button", name="Revoke").click()
            await created.wait_for(state="hidden")
            await page.get_by_text("No API keys.").wait_for(state="visible")

            await page.get_by_role("button", name="Disconnect").click()
            dialog = page.get_by_role("dialog", name="Confirm Revoke")
            await page.keyboard.press("Escape")
            await dialog.wait_for(state="hidden")
            await page.get_by_role("button", name="Disconnect").click()
            await dialog.get_by_role("button", name="Disconnect").click()
            await page.get_by_text("No clients connected.").wait_for(state="visible")
            assert await user_service.list_oauth_grants(test_user_id) == []
        finally:
            await browser.close()
