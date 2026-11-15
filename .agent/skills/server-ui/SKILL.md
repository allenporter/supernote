---
name: server-ui
description: >-
  Workflow, architecture conventions, and headless Playwright visual verification
  for iterating on the Supernote Cloud Web UI (`supernote/server/static/` and
  supporting `supernote/server/routes/` endpoints). Activate whenever adding,
  modifying, debugging, or reviewing any Web UI feature or frontend component.
---

# Server Web UI Iteration Skill

Use this workflow whenever adding, modifying, debugging, or reviewing any Web UI feature across `supernote/server/static/` and supporting server routes (`supernote/server/routes/`). For reusable Playwright harnesses, selector pitfalls, hard-won CSS/DOM/routing lessons, and the 7-point hostile UI review rubric, see [`references/ui-review-and-testing.md`](references/ui-review-and-testing.md).

## 1. Frontend Architecture & Conventions

- **No-Build Vue 3 ESM**: Components live in `supernote/server/static/js/components/`, composables in `supernote/server/static/js/composables/`, API helpers in `supernote/server/static/js/api/`, pure formatting/parsing utilities in `supernote/server/static/js/utils/format.js`, and root shell/templates in `supernote/server/static/index.html` + `supernote/server/static/js/main.js`. Do not introduce a bundler or build step.
- **Tailwind Play CDN (v3) & Dark Mode**: `index.html` loads Tailwind Play CDN (v3) and configures `tailwind.config = { darkMode: 'class' }` so OS `prefers-color-scheme: dark` does not activate partial `dark:` classes inside the light shell. Stick to Tailwind v3 utilities (`shadow-sm`, `backdrop-blur-sm`, `rounded-sm`)—avoid Tailwind v4-only classes (`shadow-2xs`, `shadow-xs`, `backdrop-blur-xs`, `rounded-xs`), which fail silently.
- **Notifications & Confirmations**: Always use `showToast` from `supernote/server/static/js/composables/useToast.js` and in-app confirmation modals (`role="dialog" aria-modal="true"`)—never `window.alert()`, `window.confirm()`, or `prompt()` (`tests/server/test_app.py` enforces zero `alert(` calls).
- **CSS, Scrolling & Touch Accessibility**:
  - Keep `.hover-reveal` actions visible under `(hover: none)` and `:focus-within` for touch screens and keyboard navigation.
  - Keep `.animate-fade-in` opacity-only so persistent `transform` values never trap `position: fixed` drawers inside `overflow-hidden` ancestors.
  - Scroll viewer containers directly via `pane.scrollTo(...)` rather than `element.scrollIntoView()` (which can shift `overflow: hidden` ancestors), and reserve `min-h-[240px] sm:min-h-[360px]` on `loading="lazy"` `.note` page images to avoid `0px` collapse and scroll-spy jumps.
  - Export pure helpers cleanly from ES modules (`utils/format.js`, `main.js`) so Playwright can unit-test them directly in Chromium.
- **API Boundary**:
  - Keep official Supernote device/cloud protocol DTOs (`supernote/models/file_device.py`, `supernote/models/file_web.py`) faithful to the official protocol.
  - Add server-specific Web UI endpoints in `supernote/server/routes/extended.py` with `DataClassJSONMixin` models in `supernote/models/extended.py` (`serialize_by_alias = True` camelCase JSON; pass 64-bit VFS IDs as strings from JS).
- **PR Granularity**: Keep UI PRs small and single-purpose on separate branches off `origin/main` (verify `git merge-tree --write-tree` when opening parallel PRs).

## 2. Testing Guardrails

- **Never write Python substring assertions on frontend source files**: Do **not** add tests in `tests/server/test_app.py` (or elsewhere) that read `.js` or `.html` files as text and run `assert "..." in js_text`.
- **Backend changes**: Add real `aiohttp` / `pytest` behavioral tests in `tests/server/routes/test_*.py` or `tests/server/services/test_*.py` asserting HTTP status codes and full JSON contracts.
- **Frontend changes**: Verify visually and behaviorally against a live ephemeral server using headless Chromium + Playwright across desktop (`1360x860`) and mobile (`375x812`) `@2x` viewports, plus run `UV_NO_SYNC=1 ./script/lint` and relevant server pytest suites (`UV_NO_SYNC=1 ./script/test tests/server/...`).

## 3. Fast Visual & Behavioral Verification Loop (Playwright)

Whenever you make a user-visible Web UI change, batch all visual captures and behavioral assertions inside a single `ephemeral_ui_session(seed="full")` server run, inspect every `@2x` PNG in `<artifacts_dir>/` with `read_file`, and audit your diff against the 7-point rubric in [`references/ui-review-and-testing.md`](references/ui-review-and-testing.md).

### Step 3.1: Capture Screenshots via [`scripts/capture_ui.py`](scripts/capture_ui.py)

Chromium is pre-cached at `~/.cache/ms-playwright`. Use `uv run --no-sync --with playwright` so `uv` layers `playwright` onto `.venv` via an ephemeral overlay without touching `pyproject.toml` or stripping `requirements_dev.txt` packages from `.venv` (if `.venv` ever needs re-bootstrapping, run `./script/bootstrap`).

For quick single-view captures (Files grid, opening `FileViewer`, Tasks, System, Search), run the bundled helper directly:

```bash
# Directory grid with seeded multi-page .note thumbnails:
uv run --no-sync --with playwright .agent/skills/server-ui/scripts/capture_ui.py \
  --output <artifacts_dir>/ui_preview.png \
  --route '/#/files/{note_dir_id}'

# Open a notebook in FileViewer before capturing:
uv run --no-sync --with playwright .agent/skills/server-ui/scripts/capture_ui.py \
  --output <artifacts_dir>/viewer_preview.png \
  --route '/#/files/{note_dir_id}' \
  --click 'text=Stroller_Design.note'

# Tasks view seeded via async_cloud_seed:
uv run --no-sync --with playwright .agent/skills/server-ui/scripts/capture_ui.py \
  --seed full \
  --route '/#/tasks' \
  --output <artifacts_dir>/tasks_preview.png
```

For full multi-view E2E, mobile, and ES-module unit verification in one fast pass, write a batched script in `<artifacts_dir>/scratch/` following [`references/ui-review-and-testing.md`](references/ui-review-and-testing.md) and run it with `uv run --no-sync --with playwright <artifacts_dir>/scratch/my_verify.py`.

### Fixture & Storage Gotchas
- **Multi-page `.note` fixtures with valid `PAGEID`s**: Prefer `tests/testdata/mmujynya/stroller.note` (2 pages) or `tests/testdata/philips/1to10.note` (10 pages). Avoid `tests/testdata/philips/test.note` for page-processing / PNG cache tests because its legacy pages lack `PAGEID`.
- **Direct blob seeding in tests**: Always import `USER_DATA_BUCKET` (`"supernote-user-data"`) and `CACHE_BUCKET` (`"supernote-cache"`) from `supernote.server.constants` rather than hardcoding bucket strings.
- **Auth injection on hash routes**: `capture_ui.py` injects `supernote_token` via `context.add_init_script(...)` before `page.goto(...)`. Never rely on `localStorage.setItem` after `page.goto(base_url)` followed by hash navigation, as ES module `client.js` reads `localStorage` once at import time.

### Step 3.2: Inspect & Audit Before Presenting
1. Call `read_file` on every generated `@2x` desktop and mobile PNG in `<artifacts_dir>/` to visually verify layout, alignment, contrast, and loading states.
2. Run the 7-point adversarial UI review checklist in [`references/ui-review-and-testing.md`](references/ui-review-and-testing.md).
3. Embed the screenshot(s) in a markdown artifact in `<artifacts_dir>/` when presenting the UI change or PR to the user.
