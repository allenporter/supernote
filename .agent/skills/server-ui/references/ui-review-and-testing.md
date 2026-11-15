# Supernote Web UI Review & Playwright Testing Reference

Detailed Playwright verification harnesses, selector pitfalls, hard-won frontend lessons, and adversarial review criteria for `supernote/server/static/` and its supporting routes.

---

## 1. Batched Single-Session Playwright Harness Pattern

Spinning up an ephemeral server and seeding fixtures for every single UI assertion adds seconds per check. Instead, launch **one** `ephemeral_ui_session(seed="full")` imported from [`../scripts/capture_ui.py`](../scripts/capture_ui.py), reuse one headless Chromium browser across desktop (`1360x860`) and mobile (`375x812`) `@2x` contexts, and run all visual captures, E2E flows, and browser ESM unit assertions inside that single session (execute with `uv run --no-sync --with playwright <script.py>`):

```python
import asyncio
import sys
from pathlib import Path
from playwright.async_api import Page, async_playwright

REPO_ROOT = Path.cwd()  # run from repository root
SCRIPTS_DIR = REPO_ROOT / ".agent/skills/server-ui/scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from capture_ui import ephemeral_ui_session  # noqa: E402


def attach_error_listeners(page: Page, errors: list[str]) -> None:
    """Record uncaught page errors, console errors, and unexpected HTTP 4xx/5xx responses."""
    page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
    page.on(
        "console",
        lambda msg: (
            errors.append(f"console.error: {msg.text}")
            if msg.type == "error"
            and "/api/extended/transcript" not in msg.text
            else None
        ),
    )

    def _on_response(resp) -> None:
        if resp.status >= 500:
            errors.append(f"HTTP {resp.status}: {resp.url}")
        elif resp.status >= 400:
            # A freshly uploaded or un-transcribed .note file returns 404 for transcript lookup.
            if resp.status == 404 and "/api/extended/transcript" in resp.url:
                return
            errors.append(f"HTTP {resp.status}: {resp.url}")

    page.on("response", _on_response)


async def run_batched_checks() -> None:
    errors: list[str] = []
    async with ephemeral_ui_session(seed="full") as session:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                # 1. Desktop (1360x860 @ 2x)
                desktop = await session.new_authenticated_context(
                    browser, width=1360, height=860, scale=2
                )
                page = await desktop.new_page()
                attach_error_listeners(page, errors)
                await page.goto(
                    f"{session.base_url}/#/files/{session.note_dir_id}",
                    wait_until="networkidle",
                )

                # Unit-test pure ES module exports directly inside Chromium
                unit_ok = await page.evaluate(
                    """async () => {
                        const mainSrc = document.querySelector('script[type="module"]').src;
                        const mainMod = await import(mainSrc);
                        const fmtMod = await import(new URL('/static/js/utils/format.js', location.origin).href);

                        const parsed = mainMod.parseUrlHash('#/files/42?page=3');
                        if (parsed.tab !== 'files' || parsed.dirId !== '42') return false;

                        const aFolder = { isDirectory: true, name: 'Beta', updateTime: 100 };
                        const bFile = { isDirectory: false, name: 'Alpha.note', updateTime: 999 };
                        if (mainMod.compareItems(aFolder, bFile, 'date', 'desc') >= 0) return false;

                        return fmtMod.normalizeEpochMs(1700000000) === 1700000000000;
                    }"""
                )
                assert unit_ok, "Pure ES module helper assertions failed"
                await page.screenshot(path="/tmp/desktop_files.png")
                await desktop.close()

                # 2. Mobile (375x812 @ 2x)
                mobile = await session.new_authenticated_context(
                    browser, width=375, height=812, scale=2
                )
                m_page = await mobile.new_page()
                attach_error_listeners(m_page, errors)
                await m_page.goto(
                    f"{session.base_url}/#/files/{session.note_dir_id}",
                    wait_until="networkidle",
                )
                overflow = await m_page.evaluate(
                    "() => document.documentElement.scrollWidth > window.innerWidth"
                )
                assert not overflow, "Mobile horizontal overflow detected at 375px"
                await m_page.screenshot(path="/tmp/mobile_files.png")
                await mobile.close()
            finally:
                await browser.close()

    assert not errors, f"Runtime browser/network errors detected: {errors}"


if __name__ == "__main__":
    asyncio.run(run_batched_checks())
```

### Teardown Note

When `ephemeral_ui_session` exits and `runner.cleanup()` cancels long-lived server background tasks, Python's event loop may print harmless `asyncio.CancelledError` messages after all Playwright assertions have already completed. Treat the script's exit code (`0`) and explicit assertions—not background task cancellation noise during teardown—as the pass/fail signal.

---

## 2. High-Frequency Playwright Locator & Assertion Pitfalls

- **Substring `get_by_text(...)` hits hidden `<option>` tags**: A generic `page.get_by_text("Modified")` or `page.get_by_text("Size")` can match `<option>` elements inside a closed `<select>` sort menu and trigger strict-mode violations or false positives. Always scope locators to interactive containers (`page.locator("main")`, `page.locator('[role="dialog"]')`) or target semantic roles (`get_by_role("button", ...)`, `get_by_role("option", ...)`), and check `.is_visible()` when visibility matters.
- **Post-delete / filtered-state text assertions match toolbar chips or empty states**: After deleting `Task Alpha` or searching/filtering down to zero results, asserting `page.get_by_text("Task Alpha").count() == 0` can fail unexpectedly if the name lingers in a search box, toast, or filter chip. Scope the assertion to the item container (e.g., `.file-card` or the task list rows container) rather than the full `page`.
- **Files List view uses CSS Grid `.divide-y > .file-card`, not `<table>`**: The List layout in `supernote/server/static/index.html` renders `<div class="divide-y divide-stone-100">` wrapping `.file-card.grid.grid-cols-12` components—not semantic `<table>` / `<tr>` / `<td>` elements. Query `.file-card` when inspecting List view rows (`Name`, `Modified`, `Size`, `Actions`); reserve `table` / `tr` locators for `SystemPanel.js`.

---

## 3. Hard-Won Frontend CSS, DOM & Routing Pitfalls

- **Tailwind Play CDN (`v3`) drops Tailwind `v4` utilities silently**: `index.html` loads `cdn.tailwindcss.com` (Tailwind v3). Classes introduced in Tailwind v4 such as `shadow-2xs`, `shadow-xs`, `backdrop-blur-xs`, and `rounded-xs` produce zero CSS rules with no console warning. Use Tailwind v3 equivalents (`shadow-sm`, `backdrop-blur-sm`, `rounded-sm`) and verify shadows/blurs visually in `@2x` screenshots.
- **Persistent CSS `transform` traps `position: fixed` drawers inside `overflow-hidden` ancestors**: Any element with a non-`none` `transform` (including keyframe endpoints that leave `transform: translateY(0)` in `forwards` mode) establishes a containing block for `position: fixed` descendants. Inside an `overflow-hidden` viewer shell, that clips slide-over drawers (such as the mobile OCR/summary drawer) to the parent box instead of pinning to the viewport. Keep `.animate-fade-in` opacity-only in `style.css`.
- **`element.scrollIntoView()` shifts `overflow: hidden` ancestors**: Calling `scrollIntoView()` on a `.note` page image inside `FileViewer.js` can scroll outer `overflow-hidden` layout wrappers and push sticky toolbars out of view. Measure offset geometry relative to `leftScrollPane` and call `pane.scrollTo({ top, behavior })` directly instead.
- **Zero-height `loading="lazy"` `.note` images cause scroll-spy jumping**: Un-decoded `<img loading="lazy">` pages without a minimum height collapse to `0px`, packing downstream pages into the initial viewport so `updateActivePageFromScroll` / `handlePageImageLoad` jumps away from Page 1 as earlier images finish loading. Reserve explicit height (`min-h-[240px] sm:min-h-[360px]`) on every page `<img>` and anchor the initial open via `jumpToTargetPage(initialTarget, { smooth: false })` without letting `@load` override the active page.
- **Competing `history.back()` vs `@open-file` & `pushState` page noise**:
  - In `SystemPanel.js` / `main.js`, navigating directly to a file via `@open-file` must not invoke a competing `window.history.back()` when closing the panel, or the popstate race overrides the newly opened file route.
  - Inside `FileViewer.js`, syncing `?page=N` should call `window.history.replaceState(...)` rather than `pushState(...)` so pressing browser Back once returns to the directory instead of stepping backward through every page scroll.
- **Vue 3 template refs require `{ flush: 'post' }`**: Watchers that touch conditional DOM nodes (such as focusing an input when a modal opens or observing `cardRef` after toggling Grid/List layout in `FileCard.js`) run before DOM patching by default; pass `{ flush: 'post' }` (or await `nextTick()`) before reading the element ref.
- **Window drag-and-drop upload guards**: Check `Array.from(event?.dataTransfer?.types || []).includes('Files')` so dragging selected text or links does not trigger the dropzone, track nested enter/leave boundaries cleanly, and always clear active drag state on `window` `dragend`, `drop`, and `Escape`.

---

## 4. 7-Point Hostile Adversarial UI Review Rubric

Audit every Web UI diff against these 7 adversarial attack vectors before considering work complete:

| # | Check | What to Attack | Concrete Pass Criteria |
| --- | --- | --- | --- |
| 1 | **CSS & CDN Fidelity** | Search static assets for Tailwind v4 classes (`shadow-2?xs`, `backdrop-blur-xs`, `rounded-xs`), orphaned font `<link>` requests, dead CSS vars, and `.dark` contrast mismatches. | 0 v4-only classes; 0 unused font requests; readable light & `.dark` contrast. |
| 2 | **Mobile `375×812` Geometry** | Check `scrollWidth > innerWidth`, overflowing header action clusters, clipped nav labels, narrow tables, and off-screen closed drawers. | `scrollWidth <= 375`; all header buttons inside viewport bounds; tables wrapped in `overflow-x-auto`; closed slide-over drawers off-screen. |
| 3 | **Touch, Keyboard & Modal A11y** | Audit hover-only controls on `(hover: none)`, native `alert`/`confirm`/`prompt`, modal `role="dialog"`, `Escape` handling, and post-mount autofocus. | `.hover-reveal` visible on touch & `:focus-within`; 0 native dialogs; modals carry `role="dialog" aria-modal="true"`, dismiss on `Escape`, and autofocus safely (`{ flush: 'post' }`). |
| 4 | **Async, Scroll & Drag Races** | Open multi-page `.note` files during lazy decode, zoom/jump pages, inspect `overflow-hidden` ancestors, and drag non-file text across the window. | Page 1 stays anchored (`min-h` reserved); `pane.scrollTo` used instead of `scrollIntoView`; opacity-only `.animate-fade-in`; `'Files'`-only dropzone with `dragend`/`drop`/`Escape` cleanup. |
| 5 | **URL & History Integrity** | Reload deep-linked routes (`#/files/...`, `?page=N`), click task hits in Search (`focusTask` -> `#/tasks`), click file IDs in System, and hit browser Back. | Deep links restore exact state; viewer page updates use `replaceState` for 1-click Back; `@open-file` never races `history.back()`. |
| 6 | **Data & Truncation Edge Cases** | Feed epoch seconds vs ms vs ISO dates (`normalizeEpochMs`), mixed folders/files with null dates/sizes, `Sort: Modified`/`Size`, and long filenames. | Folders sort first with nulls last; Modified/Size sort defaults to descending; long names truncate without colliding with badges or action buttons. |
| 7 | **Post-Edit `@2x` Visual Audit** | Re-run the batched Playwright `@2x` suite across desktop & mobile after the final edit and visually read every PNG. | 0 uncaught JS `pageerror`, `console.error`, or unexpected 4xx/5xx responses; every `@2x` desktop & mobile screenshot inspected with `read_file`. |
