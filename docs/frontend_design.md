# Supernote Cloud Web UI Architecture

The Supernote Cloud Web UI (`supernote/server/static/`) is a zero-build Vue 3 single-page application served directly by the `aiohttp` backend.

## 1. Design Principles

- **Zero Build Step**: Browser-native ES modules (`<script type="module">`) and an `<script type="importmap">` in `index.html` load pinned CDN dependencies (`vue`, `marked`, `dompurify`, `tailwindcss`, `socket.io-client`, `spark-md5`, `js-sha256`) tracked by Renovate. No `package.json`, bundler, or Node runtime is required in production containers.
- **Vue 3 Composition API**: All components use Vue 3 `setup(props, { emit, expose })` and shared composables.
- **Compile-Time Type Safety & JS Formatting/Linting**: `tsconfig.json` (`allowJs: true`, `checkJs: true`, `strict: true`) and ambient declarations (`supernote/server/static/js/types.d.ts`) strictly type-check every `.js` module via TypeScript (`tsc --noEmit`), while Biome (`biome.json`) enforces formatting, import organization, and static JavaScript lint rules in `./script/lint` and CI without transpilation.
- **Host UI Separation**: URL routing, authentication/token transport, and view shells are decoupled from domain panels so dynamic ES-module plugins can register tabs, toolbar actions, and viewer actions against a stable `PluginHostContext` contract.

## 2. Directory Layout

```text
supernote/server/static/
├── index.html                        # App shell, pinned CDN scripts & Vue 3 importmap
├── style.css                         # Custom tokens, scrollbars, and touch/focus helpers
└── js/
    ├── main.js                       # Host UI root app composition & global shortcuts
    ├── types.d.ts                    # Ambient DTOs, CDN globals & PluginHostContext contract
    ├── api/
    │   ├── http.js                   # Shared apiRequest(), token storage & 401 logout hooks
    │   ├── client.js                 # Auth, VFS CRUD, OSS upload, search, note metadata & Socket.IO
    │   └── schedule.js               # Task groups, tasks CRUD & iCalendar (.ics) feed client
    ├── composables/
    │   ├── useCanvasScrollSync.js    # Bidirectional canvas/transcript scroll sync & zoom controls
    │   ├── useModalEscape.js         # Shared LIFO Escape dismissal stack for overlays & drawers
    │   ├── useRouter.js              # Hash router (#/files, #/file/<id>?page=N, #/tasks, #/system, OAuth)
    │   ├── useFileSystem.js          # Directory listing & file mutation state
    │   ├── useProcessingStatus.js    # Background OCR/indexing status polling & digest-sync listener
    │   ├── useSchedule.js            # Task list filtering, device sort order & mutation actions
    │   └── useToast.js               # Non-blocking toast notification queue
    ├── utils/
    │   ├── clipboard.js              # Clipboard copy helper with plain-HTTP LAN fallback
    │   ├── format.js                 # Epoch ms normalization, human byte sizes & date formatting
    │   ├── markdown.js               # CommonMark + GFM Markdown renderer sanitized via DOMPurify
    │   └── oauth.js                  # OAuth 2.1 /login-bridge return_to validation & display helpers
    └── components/
        ├── FileBrowserPanel.js       # Directory browser, Grid/List switcher, multi-select & file modals
        ├── FileCard.js               # Grid, compact folder & list-row item card with lazy covers
        ├── FileViewer.js             # Split-pane document & .note canvas coordinator
        ├── viewer/
        │   ├── noteMeta.js           # Pure file category, page style, link & transcript helpers
        │   ├── ViewerToolbar.js      # Header bar, page stepper & zoom controls
        │   ├── ViewerMediaPreview.js # Inline image, PDF, text & unsupported fallback views
        │   └── ViewerSidePanel.js    # Responsive OCR transcript & summaries drawer
        ├── TaskPanel.js              # Tasks & Schedule workspace coordinator
        ├── tasks/
        │   ├── TaskSidebar.js        # Quick views, task lists & .ics export trigger
        │   ├── TaskRow.js            # Task row with due badges & hover/touch actions
        │   ├── TaskEditorModal.js    # New / Edit task dialog
        │   └── TaskIcsModal.js       # iCalendar (.ics) feed preview & download modal
        ├── LoginCard.js              # Challenge-response sign-in form
        ├── OAuthConsentCard.js       # OAuth 2.1 PKCE authorization consent screen
        ├── SearchModal.js            # Filename, transcript & semantic search dialog (Cmd/Ctrl+K)
        ├── SystemPanel.js            # Storage quota, AI status & processing queue drawer
        ├── MoveModal.js              # Folder tree destination picker
        └── RenameModal.js            # Item rename dialog
```

## 3. Linting, Type Checking & Automated Tests

- **Static Type Check & Lint**:
  ```bash
  ./script/lint
  ```
  Runs `tsc -p tsconfig.json --noEmit` (`strict: true`), `biome check --write --error-on-warnings`, `ruff`, `ty`, `codespell`, and `yamllint` via `pre-commit`.

- **Pure ES Module Unit Tests** (`node:test`, zero npm dependencies):
  ```bash
  node --import ./tests/frontend/helpers/register_vue_stub.mjs --test 'tests/frontend/**/*.test.mjs'
  ```

- **Headless Playwright E2E Smoke Suite**:
  ```bash
  uv run --no-sync --with playwright pytest tests/integration/test_web_ui.py -v
  ```
