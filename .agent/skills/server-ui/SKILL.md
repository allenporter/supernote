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

- **No-Build Vue 3 ESM + Strict TypeScript & Biome**:
  - Components live in `supernote/server/static/js/components/`, composables in `supernote/server/static/js/composables/`, API clients in `supernote/server/static/js/api/`, pure utilities in `supernote/server/static/js/utils/`, ambient DTO/Vue declarations in `supernote/server/static/js/types.d.ts`, and the host shell in `supernote/server/static/index.html` + `supernote/server/static/js/main.js`. Do not introduce a bundler, `package.json`, or Node runtime into production containers.
  - Every `.js` and `.d.ts` file is checked by TypeScript 7 (`tsconfig.json`: `checkJs: true`, `strict: true`—never reintroduce `ref(null): Ref<any>` loopholes in `types.d.ts`) and formatted/linted by Biome (`biome.json`). Note: `biome check --write` reformats modified JS files and exits non-zero on its first `./script/lint` pass; re-run `./script/lint` to verify a clean pass.
- **API Transport & Wire Normalization (`api/http.js`, `api/client.js`, `api/schedule.js`)**:
  - Route all HTTP calls through `apiRequest()` in `api/http.js` and represent HTTP errors via `export class ApiError extends Error` (`e instanceof ApiError && e.status === 401`, `getErrorMessage(e)`)—never monkey-patch `Error` instances via `Object.assign(new Error(...), { status })`.
  - Unwrap backend wire envelopes (`userFileVOList`, `summaryDOList`, `entries`, `scheduleTask`, `statusMap`, etc.) inside `api/client.js` and `api/schedule.js` so composables and components only consume normalized domain models (`FileItem`, `NoteSummary`, `ScheduleTask`, `SearchFileMatch`).
  - Keep official Supernote device/cloud protocol DTOs (`supernote/models/file_device.py`, `supernote/models/file_web.py`) faithful to the official protocol, and add Web UI endpoints in `supernote/server/routes/extended.py` with `DataClassJSONMixin` models in `supernote/models/extended.py` (`serialize_by_alias = True`; pass 64-bit VFS IDs as strings from JS).
- **Tailwind Play CDN (v3) & Dark Mode**: `index.html` loads Tailwind Play CDN (v3) and configures `tailwind.config = { darkMode: 'class' }` so OS `prefers-color-scheme: dark` does not activate partial `dark:` classes inside the light shell. Stick to Tailwind v3 utilities (`shadow-sm`, `backdrop-blur-sm`, `rounded-sm`)—avoid Tailwind v4-only classes (`shadow-2xs`, `shadow-xs`, `backdrop-blur-xs`, `rounded-xs`), which fail silently.
- **Modals, Overlays & Notifications**:
  - Always use `showToast` (`composables/useToast.js`) and in-app confirmation modals (`role="dialog" aria-modal="true"`)—never `window.alert()`, `window.confirm()`, or `prompt()` (`biome.json` enforces `noAlert: "error"`).
  - Register all modal and mobile-drawer `Escape` dismissal via `useModalEscape()` (`composables/useModalEscape.js`)—never attach per-component `window.addEventListener('keydown', ...)` listeners, which fire in FIFO order and dismiss underlying modals when overlays stack.
  - Follow the overlay z-index hierarchy: `z-40` dropzone < `z-50` sticky header < `z-[60]`/`z-[70]` mobile viewer drawer < `z-[100]` creation/export modals < `z-[110]` confirmation/move/rename modals < `z-[120]` `SystemPanel` < `z-[150]` `SearchModal` < `z-[200]` toasts.
  - Wrap modal inputs in `<form @submit.prevent>` with an `isSubmitting` guard, keep modals open with user input intact when a save fails, and reset transient session/modal/toast state on `onLogout`.
- **CSS, Scrolling, Keyboard & Touch Accessibility**:
  - Keep `.hover-reveal` actions visible under `(hover: none)` and `:focus-within`; hide closed off-screen mobile drawers from `Tab` order using `invisible pointer-events-none md:visible md:pointer-events-auto`.
  - Keep `.animate-fade-in` opacity-only so persistent `transform` values never trap `position: fixed` drawers inside `overflow-hidden` ancestors.
  - Scroll viewer containers directly via `pane.scrollTo(...)` rather than `element.scrollIntoView()`, and reserve `min-h-[240px] sm:min-h-[360px]` on `loading="lazy"` `.note` page images to avoid `0px` collapse and scroll-spy jumps.
- **PR Granularity**: Keep UI PRs small (~150–300 LoC) and single-purpose on separate branches off `origin/main` (verify `git merge-tree --write-tree` when opening parallel PRs).

## 2. Testing Guardrails

- **Never write Python substring assertions on frontend source files**: Do **not** add tests in `tests/server/test_app.py` (or elsewhere) that read `.js` or `.html` files as text and run `assert "..." in js_text`.
- **1:1 Frontend ESM Unit Suite (`tests/frontend/*.test.mjs`)**: Add or update matching `node:test` modules for every `api/`, `composables/`, and `utils/` change (using `mountComposable()` from `tests/frontend/helpers/vue_test_scope.mjs` and `t.mock.timers.enable({ apis: ['setTimeout'] })` instead of wall-clock `setTimeout` sleeps):
  ```bash
  node --import ./tests/frontend/helpers/register_vue_stub.mjs --test 'tests/frontend/**/*.test.mjs'
  ```
- **Backend changes**: Add real `aiohttp` / `pytest` behavioral tests in `tests/server/routes/test_*.py` or `tests/server/services/test_*.py` asserting HTTP status codes and full JSON contracts.
- **Playwright E2E & Visual Verification**: Run `uv run --no-sync --with playwright pytest tests/integration/test_web_ui.py -v` and verify user-visible UI changes across desktop (`1360x860`) and mobile (`375x812`) `@2x` viewports, plus `./script/lint`.

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
