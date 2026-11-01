---
name: server-ui
description: >-
  Workflow, architecture conventions, and headless Playwright visual verification
  for iterating on the Supernote Cloud Web UI (`supernote/server/static/` and
  supporting `supernote/server/routes/` endpoints). Activate whenever adding,
  modifying, debugging, or reviewing any Web UI feature or frontend component.
---

# Server Web UI Iteration Skill

Use this workflow whenever adding, modifying, debugging, or reviewing any Web UI feature across `supernote/server/static/` and supporting server routes (`supernote/server/routes/`).

## 1. Frontend Architecture & Conventions

- **No-Build Vue 3 ESM**: Components live in `supernote/server/static/js/components/`, composables in `supernote/server/static/js/composables/`, API helpers in `supernote/server/static/js/api/`, and root shell/templates in `supernote/server/static/index.html` + `supernote/server/static/js/main.js`.
- **Tailwind Play CDN & Dark Mode**: `index.html` configures `tailwind.config = { darkMode: 'class' }` so OS `prefers-color-scheme: dark` does not activate partial `dark:` classes inside the light shell.
- **Notifications**: Always use `showToast` from `supernote/server/static/js/composables/useToast.js`—never `window.alert()` (`tests/server/test_app.py` enforces zero `alert(` calls).
- **API Boundary**:
  - Keep official Supernote device/cloud protocol DTOs (`supernote/models/file_device.py`, `supernote/models/file_web.py`) faithful to the official protocol.
  - Add server-specific Web UI endpoints in `supernote/server/routes/extended.py` with `DataClassJSONMixin` models in `supernote/models/extended.py` (`serialize_by_alias = True` camelCase JSON; pass 64-bit VFS IDs as strings from JS).
- **PR Granularity**: Keep UI PRs small and single-purpose on separate branches off `origin/main` (verify `git merge-tree --write-tree` when opening parallel PRs).

## 2. Testing Guardrails

- **Never write Python substring assertions on frontend source files**: Do **not** add tests in `tests/server/test_app.py` (or elsewhere) that read `.js` or `.html` files as text and run `assert "..." in js_text`.
- **Backend changes**: Add real `aiohttp` / `pytest` behavioral tests in `tests/server/routes/test_*.py` or `tests/server/services/test_*.py` asserting HTTP status codes and full JSON contracts.
- **Frontend changes**: Verify visually and behaviorally against a live ephemeral server using headless Chromium + Playwright (below), plus run `UV_PYTHON=3.13 UV_NO_SYNC=1 ./script/lint` and relevant server pytest suites.

## 3. Visual Verification & Screenshot Workflow (Playwright)

Whenever you make a user-visible Web UI change, render a `@2x` screenshot against an in-process ephemeral server into `<artifacts_dir>/`, inspect it with `read_file`, and embed it in a markdown artifact when presenting the change/PR.

### Step 3.1: Ensure Playwright is Available in `.venv`

Chromium is pre-cached at `~/.cache/ms-playwright`. Install only the Python driver into the existing Python 3.13 `.venv` without modifying `pyproject.toml` or recreating `.venv`:

```bash
.venv/bin/python -c "import playwright" 2>/dev/null || uv pip install playwright
```

> **Important**: Never run bare `uv run --with playwright ...` without `--no-project`, as `uv run` may recreate `.venv` with a different Python version. Always keep `.venv` on Python 3.13 (`UV_PYTHON=3.13 ./script/bootstrap` if `.venv` ever needs restoration).

### Step 3.2: Capture Screenshots via [`scripts/capture_ui.py`](scripts/capture_ui.py)

For standard views (Files grid, opening `FileViewer`, Tasks, System, Search), run the bundled helper directly:

```bash
# Directory grid with seeded multi-page .note thumbnails:
.venv/bin/python .agent/skills/server-ui/scripts/capture_ui.py \
  --output <artifacts_dir>/ui_preview.png \
  --route '/#/files/{note_dir_id}'

# Open a notebook in FileViewer before capturing:
.venv/bin/python .agent/skills/server-ui/scripts/capture_ui.py \
  --output <artifacts_dir>/viewer_preview.png \
  --route '/#/files/{note_dir_id}' \
  --click 'text=Stroller_Design.note'

# Tasks view seeded via async_cloud_seed:
.venv/bin/python .agent/skills/server-ui/scripts/capture_ui.py \
  --seed full \
  --route '/#/tasks' \
  --output <artifacts_dir>/tasks_preview.png
```

For custom multi-step interactions or custom data setups (e.g. seeding 65 folders to test pagination), write a short script in `<artifacts_dir>/scratch/` importing `ephemeral_ui_session` from `.agent/skills/server-ui/scripts/capture_ui.py`.

### Fixture & Storage Gotchas
- **Multi-page `.note` fixtures with valid `PAGEID`s**: Prefer `tests/testdata/mmujynya/stroller.note` (2 pages) or `tests/testdata/philips/1to10.note` (10 pages). Avoid `tests/testdata/philips/test.note` for page-processing / PNG cache tests because its legacy pages lack `PAGEID`.
- **Direct blob seeding in tests**: Always import `USER_DATA_BUCKET` (`"supernote-user-data"`) and `CACHE_BUCKET` (`"supernote-cache"`) from `supernote.server.constants` rather than hardcoding bucket strings.
- **Auth injection on hash routes**: `capture_ui.py` injects `supernote_token` via `context.add_init_script(...)` before `page.goto(...)`. Never rely on `localStorage.setItem` after `page.goto(base_url)` followed by hash navigation, as ES module `client.js` reads `localStorage` once at import time.

### Step 3.3: Inspect & Present
1. Call `read_file` on the generated `.png` in `<artifacts_dir>/` to visually verify layout, alignment, contrast, and loading states.
2. Embed the screenshot(s) in a markdown artifact in `<artifacts_dir>/` when presenting the UI change or PR to the user.
