"""End-to-end headless Playwright smoke tests for the Supernote Cloud Web UI.

Automatically skipped when Playwright (or its Chromium browser binary) is not
installed in minimal Python environments, and executed in CI via
`.github/workflows/frontend.yaml`.
"""

import asyncio
import re
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient
from sqlalchemy import select

from supernote.client.client import Client
from supernote.client.schedule import ScheduleClient
from supernote.client.web import WebClient
from supernote.models.summary import (
    AddSummaryDTO,
    AddSummaryGroupDTO,
    QuerySummaryGroupDTO,
)
from supernote.server.components.processor import PROCESSOR_SERVICE_KEY
from supernote.server.components.summary import SUMMARY_SERVICE_KEY
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.summary import SummaryTranscriptDO
from supernote.server.keys import (
    SESSION_MANAGER_KEY,
    USER_SERVICE_KEY,
)
from tests.fixtures.oauth import TEST_CLIENT_ID, TEST_REDIRECT_URI, FakeDocumentFetcher

SAMPLE_UI_NOTE = Path(__file__).resolve().parents[1] / "testdata/philips/1to10.note"


async def test_web_ui_desktop_and_mobile_smoke(
    client: TestClient,
    authenticated_client: Client,
    web_client: WebClient,
    auth_headers: dict[str, str],
    admin_user_id: int,
) -> None:
    """Verify core desktop and mobile Web UI flows with zero runtime errors."""
    _ = admin_user_id
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
            export_pdf_btn = page.get_by_role("button", name="Export PDF")
            await export_pdf_btn.wait_for(state="visible")
            async with page.expect_download(timeout=15000) as download_info:
                await export_pdf_btn.click()
            pdf_download = await download_info.value
            assert pdf_download.suggested_filename == "Numbered_1to10.pdf"
            pdf_download_path = await pdf_download.path()
            assert pdf_download_path is not None
            assert Path(pdf_download_path).read_bytes().startswith(b"%PDF-")

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

            # Unified Settings & System modal (#/settings and #/system tabs) + global search modal
            await page.get_by_role("button", name="Settings").click()
            assert page.url.endswith("#/settings")
            await page.get_by_role("button", name="System & Queue").click()
            assert page.url.endswith("#/system")
            await page.get_by_role("heading", name="Server Components").wait_for(
                state="visible"
            )
            await page.get_by_role("heading", name="Recent Notebook Activity").wait_for(
                state="visible"
            )
            await page.get_by_role("link", name="Numbered_1to10.note").first.wait_for(
                state="visible"
            )
            await page.get_by_role("button", name="Stage Log").click()
            await page.get_by_text("Page Hash").first.wait_for(state="visible")
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


async def test_web_ui_digests_browser_view(
    client: TestClient,
    auth_headers: dict[str, str],
    web_client: WebClient,
) -> None:
    """Verify #/digests browses categories, standalone device digests, sources, and deep-links."""
    playwright_async = pytest.importorskip("playwright.async_api")
    assert client.app is not None

    root_list = await web_client.list_query(0)
    note_dir_id = next(
        int(item.id)
        for item in root_list.user_file_vo_list
        if item.is_folder == "Y" and item.file_name == "Note"
    )
    await web_client.upload_file(
        note_dir_id, "Digest_Source.note", SAMPLE_UI_NOTE.read_bytes()
    )
    await asyncio.wait_for(client.app[PROCESSOR_SERVICE_KEY].queue.join(), timeout=15.0)
    note_list = await web_client.list_query(note_dir_id)
    note_file_id = int(
        next(
            f.id
            for f in note_list.user_file_vo_list
            if f.file_name == "Digest_Source.note"
        )
    )

    user_email = (await web_client.query_user()).email
    assert user_email is not None
    summary_service = client.app[SUMMARY_SERVICE_KEY]
    await summary_service.add_group(
        user_email,
        AddSummaryGroupDTO(
            unique_identifier="a" * 32,
            name="AI Summaries",
            md5_hash="0123456789abcdef",
        ),
    )
    await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=note_file_id,
            unique_identifier="b" * 32,
            parent_unique_identifier="a" * 32,
            content="## Weekly Architecture Recap\n- **Shipped** Digests browser view",
            data_source="GEMINI",
            source_path="Note/Digest_Source.note",
        ),
    )
    hw_digest = await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=None,
            unique_identifier="c" * 32,
            parent_unique_identifier="",
            content="Simplicity is prerequisite for reliability.",
            comment_str="Apply this to sync state",
            metadata='{"author": "Edsger Dijkstra"}',
            source_path="Document/Papers/Reliability.pdf",
            handwrite_inner_name="hw-blob-001",
            handwrite_md5="hw-md5-001",
            tags="classic, engineering",
        ),
    )
    assert hw_digest.id is not None
    user_id = await client.app[USER_SERVICE_KEY].get_user_id(user_email)
    assert user_id is not None
    async with client.app[SESSION_MANAGER_KEY].session() as session:
        session.add(
            SummaryTranscriptDO(
                user_id=user_id,
                summary_id=hw_digest.id,
                handwrite_md5="hw-md5-001",
                text_content="Keep state machines minimal and deterministic",
                model_id="gemini-2.5-flash",
            )
        )
        await session.commit()
    await summary_service.add_summary(
        user_email,
        AddSummaryDTO(
            file_id=None,
            unique_identifier="d" * 32,
            parent_unique_identifier="",
            content="Make illegal states unrepresentable.",
            handwrite_inner_name="hw-blob-pending",
            handwrite_md5="hw-md5-pending",
        ),
    )

    base_url = str(client.make_url("")).rstrip("/")
    token = auth_headers["x-access-token"]
    errors: list[str] = []

    async with playwright_async.async_playwright() as p:
        try:
            browser = await p.chromium.launch()
        except playwright_async.Error as exc:
            pytest.skip(f"Chromium browser binary not installed: {exc}")
        try:
            desktop = await browser.new_context(viewport={"width": 1360, "height": 860})
            await desktop.add_init_script(
                f"localStorage.setItem('supernote_token', {token!r});"
            )
            page = await desktop.new_page()
            page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
            page.on(
                "console",
                lambda msg: (
                    errors.append(f"console.error: {msg.text}")
                    if msg.type == "error"
                    else None
                ),
            )

            await page.goto(f"{base_url}/#/files", wait_until="networkidle")
            await page.get_by_role("button", name="Digests", exact=True).click()
            assert page.url.endswith("#/digests")

            await page.get_by_text("Weekly Architecture Recap").wait_for(
                state="visible"
            )
            await page.get_by_text("Edsger Dijkstra").wait_for(state="visible")
            await page.get_by_text("Apply this to sync state").wait_for(state="visible")
            await page.get_by_text("Handwritten", exact=True).first.wait_for(
                state="visible"
            )
            await page.get_by_text(
                "Keep state machines minimal and deterministic"
            ).wait_for(state="visible")
            await page.get_by_text(
                "Handwritten annotation attached — transcript pending."
            ).wait_for(state="visible")

            await page.get_by_role(
                "button", name=re.compile(r"^Uncategorized\b")
            ).click()
            await page.get_by_text(
                "Simplicity is prerequisite for reliability."
            ).wait_for(state="visible")
            await page.get_by_text("Weekly Architecture Recap").wait_for(state="hidden")

            await page.get_by_role(
                "button", name=re.compile(r"^AI Summaries\b")
            ).click()
            await page.get_by_text("Weekly Architecture Recap").wait_for(
                state="visible"
            )
            await page.get_by_role("button", name="Open Source").click()
            await page.wait_for_url(f"**/#/file/{note_file_id}*")
            await desktop.close()

            mobile = await browser.new_context(viewport={"width": 375, "height": 812})
            await mobile.add_init_script(
                f"localStorage.setItem('supernote_token', {token!r});"
            )
            mpage = await mobile.new_page()
            mpage.on("pageerror", lambda exc: errors.append(f"mobile pageerror: {exc}"))
            await mpage.goto(f"{base_url}/#/digests", wait_until="networkidle")
            await mpage.get_by_text("Weekly Architecture Recap").wait_for(
                state="visible"
            )
            overflow = await mpage.evaluate(
                "document.documentElement.scrollWidth - window.innerWidth"
            )
            assert overflow <= 0, f"Mobile digests horizontal overflow: {overflow}px"
            await mobile.close()
        finally:
            await browser.close()

    assert not errors, f"Unexpected browser errors in Digests view: {errors}"


async def test_web_ui_digests_crud_modals(
    client: TestClient,
    auth_headers: dict[str, str],
    web_client: WebClient,
) -> None:
    """Verify creating, renaming, editing, moving, and deleting digests & categories in #/digests."""
    playwright_async = pytest.importorskip("playwright.async_api")
    assert client.app is not None
    user_email = (await web_client.query_user()).email
    assert user_email is not None
    summary_service = client.app[SUMMARY_SERVICE_KEY]

    base_url = str(client.make_url("")).rstrip("/")
    token = auth_headers["x-access-token"]
    errors: list[str] = []

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
            page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
            page.on(
                "console",
                lambda msg: (
                    errors.append(f"console.error: {msg.text}")
                    if msg.type == "error"
                    else None
                ),
            )

            await page.goto(f"{base_url}/#/digests", wait_until="networkidle")

            # Create and rename a category
            await page.get_by_role("button", name="+ New").click()
            cat_dialog = page.get_by_role("dialog", name="New Category")
            await cat_dialog.get_by_label("Category Name").fill("Reading List")
            await cat_dialog.get_by_role("button", name="Create").click()
            await cat_dialog.wait_for(state="hidden")

            await page.get_by_role(
                "button", name="Rename category Reading List"
            ).click()
            rename_dialog = page.get_by_role("dialog", name="Rename Category")
            await rename_dialog.get_by_label("Category Name").fill("Classic Papers")
            await rename_dialog.get_by_role("button", name="Rename").click()
            await rename_dialog.wait_for(state="hidden")

            groups = await summary_service.list_groups(
                user_email, QuerySummaryGroupDTO(page=1, size=0)
            )
            assert [g.name for g in groups] == ["Classic Papers"]

            # Create a digest inside Classic Papers
            await page.get_by_role(
                "button", name=re.compile(r"^Classic Papers\b")
            ).click()
            await page.get_by_role("button", name="New Digest").click()
            editor = page.get_by_role("dialog", name="New Digest")
            await editor.get_by_label("Content").fill("Design for clarity first.")
            await editor.get_by_label("Comment").fill("Key takeaway")
            await editor.get_by_label("Author").fill("Tony Hoare")
            await editor.get_by_label("Source Path").fill("Document/Hoare.pdf")
            await editor.get_by_role("button", name="Create Digest").click()
            await editor.wait_for(state="hidden")
            await page.get_by_text("Design for clarity first.").wait_for(
                state="visible"
            )

            # Edit & move digest to Uncategorized
            await page.get_by_role("button", name="Edit digest").click()
            edit_dialog = page.get_by_role("dialog", name="Edit Digest")
            await edit_dialog.get_by_label("Category").select_option("")
            await edit_dialog.get_by_label("Content").fill("Clarity beats cleverness.")
            await edit_dialog.get_by_role("button", name="Save Changes").click()
            await edit_dialog.wait_for(state="hidden")

            saved = await summary_service.list_summaries(user_email, page=1, size=0)
            assert len(saved) == 1
            assert saved[0].content == "Clarity beats cleverness."
            assert saved[0].parent_unique_identifier == ""

            # Escape cancels delete confirmation; confirming removes the digest
            await page.get_by_role("button", name=re.compile(r"^All Digests\b")).click()
            await page.get_by_text("Clarity beats cleverness.").wait_for(
                state="visible"
            )
            await page.get_by_role("button", name="Delete digest").click()
            confirm_dialog = page.get_by_role("dialog", name="Confirm Delete")
            await confirm_dialog.wait_for(state="visible")
            await page.keyboard.press("Escape")
            await confirm_dialog.wait_for(state="hidden")

            await page.get_by_role("button", name="Delete digest").click()
            await confirm_dialog.get_by_role("button", name="Delete").click()
            await confirm_dialog.wait_for(state="hidden")
            assert (
                await summary_service.list_summaries(user_email, page=1, size=0) == []
            )

            # Deleting a category cascades to its child digests
            await page.get_by_role(
                "button", name=re.compile(r"^Classic Papers\b")
            ).click()
            await page.get_by_role("button", name="New Digest").click()
            editor = page.get_by_role("dialog", name="New Digest")
            await editor.get_by_label("Content").fill("Child digest")
            await editor.get_by_role("button", name="Create Digest").click()
            await editor.wait_for(state="hidden")
            await page.get_by_text("Child digest").wait_for(state="visible")

            await page.get_by_role(
                "button", name="Delete category Classic Papers"
            ).click()
            await confirm_dialog.get_by_role("button", name="Delete").click()
            await confirm_dialog.wait_for(state="hidden")

            assert (
                await summary_service.list_groups(
                    user_email, QuerySummaryGroupDTO(page=1, size=0)
                )
                == []
            )
            assert (
                await summary_service.list_summaries(user_email, page=1, size=0) == []
            )
            await context.close()
        finally:
            await browser.close()

    assert not errors, f"Unexpected browser errors in Digests CRUD modals: {errors}"


def _held_until(release: asyncio.Event) -> Any:
    """A Playwright route handler that lets requests through once `release` is set."""

    async def hold(route: Any) -> None:
        await release.wait()
        await route.continue_()

    return hold


@pytest.mark.parametrize("mcp_enabled", [True])
async def test_web_ui_consent_card_shows_the_resolved_client(
    client_metadata_documents: FakeDocumentFetcher,
    client: TestClient,
    auth_headers: dict[str, str],
    mcp_enabled: bool,
) -> None:
    """The consent card names the client from its metadata document and its real redirect."""
    playwright_async = pytest.importorskip("playwright.async_api")
    base_url = str(client.make_url("")).rstrip("/")
    token = auth_headers["x-access-token"]
    bridge = f"{base_url}/login-bridge?client_id={TEST_CLIENT_ID}&code_challenge=abc123"
    errors: list[str] = []
    expected_errors: set[tuple[int, str]] = set()

    def attach_listeners(page: Any) -> None:
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
        # Failed-resource console lines are left to the response listener below,
        # which can tell an expected 400/503 from an unexpected one.
        page.on(
            "console",
            lambda msg: (
                errors.append(f"console.error: {msg.text}")
                if msg.type == "error" and "status of" not in msg.text
                else None
            ),
        )

        def on_response(resp: Any) -> None:
            if resp.status >= 400 and (
                (resp.status, resp.url.split("?")[0]) not in expected_errors
            ):
                errors.append(f"HTTP {resp.status}: {resp.url}")

        page.on("response", on_response)

    async with playwright_async.async_playwright() as p:
        try:
            browser = await p.chromium.launch()
        except playwright_async.Error as exc:
            pytest.skip(f"Chromium browser binary not installed: {exc}")
        try:
            for width, height in ((1360, 860), (375, 812)):
                context = await browser.new_context(
                    viewport={"width": width, "height": height}
                )
                await context.add_init_script(
                    f"localStorage.setItem('supernote_token', {token!r});"
                )
                await context.route(
                    "https://client.example/**",
                    lambda route: route.fulfill(status=200, body="signed in"),
                )
                release = asyncio.Event()
                await context.route("**/login-bridge/client?*", _held_until(release))
                page = await context.new_page()
                attach_listeners(page)
                await page.goto(f"{bridge}&state=st")

                card = page.get_by_role("region", name="Authorize Application")
                await card.get_by_test_id("oauth-client-loading").wait_for()
                assert await card.get_by_test_id(
                    "oauth-redirect-host"
                ).inner_text() == ("Resolving...")
                assert await card.get_by_role("button", name="Approve").is_disabled()
                assert await card.get_by_role("button", name="Deny").is_disabled()

                release.set()
                await card.get_by_test_id("oauth-client-name").wait_for()
                assert await card.get_by_test_id("oauth-client-name").inner_text() == (
                    "Example Client"
                )
                assert await card.get_by_test_id("oauth-client-host").inner_text() == (
                    "client.example"
                )
                assert await card.get_by_test_id("oauth-redirect-uri").inner_text() == (
                    TEST_REDIRECT_URI
                )
                approve = card.get_by_role("button", name="Approve")
                assert await approve.is_enabled()
                assert await approve.evaluate("el => el === document.activeElement")
                assert not await page.evaluate(
                    "() => document.documentElement.scrollWidth > window.innerWidth"
                )

                await approve.click()
                await page.wait_for_url(
                    re.compile(r"^https://client\.example/callback\?")
                )
                assert "code=" in page.url and "state=st" in page.url
                await context.close()

            context = await browser.new_context(viewport={"width": 1360, "height": 860})
            await context.add_init_script(
                f"localStorage.setItem('supernote_token', {token!r});"
            )
            client_requests = 0

            async def flaky(route: Any) -> None:
                nonlocal client_requests
                client_requests += 1
                if client_requests == 1:
                    await route.fulfill(
                        status=503,
                        json={
                            "error": "temporarily_unavailable",
                            "error_description": "The client's metadata document could not be fetched.",
                        },
                    )
                else:
                    await route.continue_()

            await context.route("**/login-bridge/client?*", flaky)
            expected_errors.add((503, f"{base_url}/login-bridge/client"))
            expected_errors.add((400, f"{base_url}/login-bridge/client"))
            page = await context.new_page()
            attach_listeners(page)
            await page.goto(bridge)
            card = page.get_by_role("region", name="Authorize Application")
            banner = card.get_by_test_id("oauth-client-error")
            await banner.wait_for()
            assert "could not be fetched. Try again in a few seconds." in (
                await banner.inner_text()
            )
            retry = banner.get_by_role("button", name="Retry")
            assert await retry.evaluate("el => el === document.activeElement")
            assert await card.get_by_role("button", name="Approve").is_disabled()
            await retry.click()
            await card.get_by_test_id("oauth-client-name").wait_for()
            assert await banner.count() == 0

            client_metadata_documents.documents[
                "https://client.example/invalid.json"
            ] = {"client_id": "someone-else"}
            await page.goto(
                f"{base_url}/login-bridge?client_id=https://client.example/invalid.json"
                "&code_challenge=abc123"
            )
            heading = page.get_by_role("heading", name="Invalid Authorization Request")
            await heading.wait_for()
            assert await page.get_by_role("button", name="Approve").count() == 0
            await context.close()
        finally:
            await browser.close()

    assert not errors, f"Unexpected browser errors: {errors}"


async def test_web_ui_minimal_components_disabled(
    tmp_path: Path,
    aiohttp_client: Any,
) -> None:
    """Core Web UI flows work with zero 404s or runtime errors when optional components are disabled."""
    import yaml  # noqa: PLC0415

    from supernote.client.auth import ConstantAuth  # noqa: PLC0415
    from supernote.client.login_client import LoginClient  # noqa: PLC0415
    from supernote.server.app import bootstrap_ephemeral_user, create_app  # noqa: PLC0415
    from supernote.server.config import AuthConfig, ServerConfig  # noqa: PLC0415

    playwright_async = pytest.importorskip("playwright.async_api")

    disabled_domains = (
        "ai",
        "conversion",
        "mcp",
        "note_metadata",
        "processor",
        "schedule",
        "search",
        "summary",
        "transcript",
        "wiki",
    )
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        yaml.safe_dump({domain: {"enabled": False} for domain in disabled_domains})
    )
    cfg = ServerConfig.load(config_file=cfg_file)
    cfg.storage_dir = str(tmp_path / "storage")
    cfg.auth = AuthConfig(
        enable_registration=True,
        secret_key="minimal-ui-test-secret-key-32-bytes!",
    )

    app = create_app(cfg)
    minimal_client: TestClient = await aiohttp_client(app)
    await bootstrap_ephemeral_user(app)
    base_url = str(minimal_client.make_url("")).rstrip("/")

    login_client = LoginClient(Client(minimal_client.session, host=base_url))
    token = await login_client.login("debug@example.com", "password")
    wc = WebClient(
        Client(minimal_client.session, auth=ConstantAuth(token), host=base_url)
    )
    root = await wc.list_query(0)
    note_dir_id = next(
        int(item.id)
        for item in root.user_file_vo_list
        if item.is_folder == "Y" and item.file_name == "Note"
    )
    await wc.upload_file(note_dir_id, "Minimal_Test.note", SAMPLE_UI_NOTE.read_bytes())

    errors: list[str] = []

    def attach_listeners(page: Any) -> None:
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
        page.on(
            "console",
            lambda msg: (
                errors.append(f"console.error: {msg.text}")
                if msg.type == "error"
                else None
            ),
        )
        page.on(
            "response",
            lambda resp: (
                errors.append(f"HTTP {resp.status}: {resp.request.method} {resp.url}")
                if resp.status >= 400
                else None
            ),
        )

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
            attach_listeners(page)

            # 1. Unavailable tab deep link redirects to Files and hides optional tabs.
            await page.goto(f"{base_url}/#/wiki/projects/alpha")
            await page.get_by_role("button", name="Files", exact=True).wait_for()
            await page.wait_for_function("() => window.location.hash === '#/files'")
            for hidden_tab in ("Digests", "Tasks", "Wiki"):
                assert (
                    await page.locator(
                        f"header button:has-text('{hidden_tab}')"
                    ).count()
                    == 0
                )

            # 2. Browse Note folder and open a notebook in FileViewer.
            await page.goto(f"{base_url}/#/files/{note_dir_id}")
            await page.get_by_text("Minimal_Test.note").wait_for()
            await page.get_by_text("Minimal_Test.note").click()
            await page.get_by_text(
                "Page rendering is disabled on this server."
            ).wait_for()
            await page.get_by_text(
                "Handwriting transcription is disabled on this server."
            ).wait_for()
            assert await page.locator("button:has-text('Summaries')").count() == 0

            # 3. Global Search finds files by name without hitting semantic or schedule APIs.
            await page.goto(f"{base_url}/#/files")
            await page.keyboard.press("Control+k")
            search_input = page.get_by_role("textbox", name="Global Search")
            await search_input.wait_for()
            await search_input.fill("Minimal_Test")
            await page.get_by_text("Minimal_Test.note", exact=True).wait_for()
            await page.keyboard.press("Escape")

            # 4. System panel shows DISABLED queue banner and hides AI/activity sections.
            await page.goto(f"{base_url}/#/system")
            await page.get_by_text("Background processing is disabled").wait_for()
            await page.get_by_text("Storage Usage").wait_for()
            assert await page.get_by_text("AI Processing Pipeline").count() == 0
            assert await page.get_by_text("Recent Notebook Activity").count() == 0

            await context.close()
        finally:
            await browser.close()

    assert not errors, f"Unexpected errors with optional components disabled: {errors}"
