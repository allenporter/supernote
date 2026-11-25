# Release QA Checklist

Release QA verifies the **upgrade path, packaging, and real user journeys** on the target `origin/main` commit—not just re-running unit tests CI already executed.

Record pass/fail (and any blockers or caveats) for each section before cutting a release.

---

## 1. Automated Quality Gates

- [ ] Target commit is up to date with `origin/main` and has green CI (`test`, `lint`, `frontend`, `docker`, `pages`).
- [ ] `./script/lint` passes with zero warnings or formatting diffs (ruff, ty, biome, tsc).
- [ ] `./script/test` passes (Python + frontend unit suites).
- [ ] `./script/docs` builds cleanly with no broken links or pdoc errors.

## 2. Database Upgrade & Migration Safety

Inspect `git diff --name-status <prev-tag>..origin/main -- supernote/alembic/versions/`.

- [ ] **Fresh database**: Server boots against an empty data directory and runs all migrations cleanly to `head`.
- [ ] **Upgrade from `<prev-tag>`** *(required whenever migrations were added/modified)*:
  - Seed a SQLite database at `<prev-tag>` schema (with representative user/file/task/summary data).
  - Boot the candidate code against that database and confirm automatic startup migrations succeed with existing data intact.
- [ ] **Schema drift check**: `uv run --no-sync alembic check` reports no undetected ORM/migration drift.
- [ ] **Multi-user scoping**: Migration and component conformance tests (`tests/server/db/test_migrations.py`, `tests/server/components/test_init.py`) pass without new allowlist exemptions.

## 3. Zero-AI / Optionality & Config Compatibility

- [ ] **Zero-AI baseline**: Server boots cleanly with no AI provider configured and default opt-in components disabled (verifying disabled optional components are not required at startup).
- [ ] **Config compatibility**: A `<prev-tag>`-era `config.yaml` and environment variables load without errors or unexpected behavior changes.
- [ ] **Breaking/behavioral changes audit**: Review diffs touching `config-example.yaml`, `supernote/server/config.py`, `supernote/server/components/*/config.py`, webhooks/events, REST routes, CLI flags, and MCP tool signatures to confirm whether any breaking changes or deprecation notices are needed.

## 4. End-to-End Smoke of Headline Changes

Identify every user-facing feature or bug fix merged since `<prev-tag>` and exercise it on a live ephemeral server:

- [ ] **Web UI**: Start an ephemeral server and verify new/modified Web UI flows with headless Playwright (see the `server-ui` skill). Check for zero browser console errors, zero uncaught page errors, and zero server 500s.
- [ ] **CLI & MCP**: Spot-check new or changed `supernote` CLI subcommands and MCP tools against the running server.
- [ ] **Key edge cases**: Test error states, empty states, and permission/user-isolation boundaries for newly added endpoints or UI flows.

## 5. Packaging & Distribution Sanity

- [ ] **Build distributions**: `uv run --no-sync python -m build` produces both `.whl` and `.tar.gz` cleanly.
- [ ] **Inspect wheel contents**: Verify bundled non-Python assets are present inside the wheel (`supernote/server/static/`, `supernote/alembic/`, templates, prompts, `py.typed`, etc.).
- [ ] **Clean-venv install smoke**: Install the built `.whl` into an isolated temporary virtual environment and verify `supernote --help` and basic server startup work outside the source tree.
- [ ] **Docker**: Confirm the `Docker` GitHub Actions workflow passed on `origin/main` (or test `docker build` locally if `Dockerfile` / runtime deps changed).

## 6. Release Hygiene

- [ ] **Version number**: SemVer bump matches the scope of changes since `<prev-tag>`.
- [ ] **Security & privacy**: Any security fixes are verified and clearly noted without exposing sensitive details prematurely.
- [ ] **Release notes parity**: Every feature, migration ID, config key, CLI flag, and MCP tool mentioned in the release notes has been verified against `origin/main`.
