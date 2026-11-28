---
name: project_development
description: Use standardized scripts to manage the project environment, testing, and linting.
---

# Project Development Skill

This skill teaches you how to interact with the Supernote codebase using standardized scripts, following the "Scripts to Rule Them All" pattern.

## Core Scripts

| Script | When to use |
| :--- | :--- |
| `script/bootstrap` | After cloning or when dependencies change. |
| `script/test` | Before submitting changes or to verify functionality. |
| `script/lint` | Before committing to ensure code style and quality. |
| `script/server` | When you need a running server for integration testing or manual verification. |
| `script/db_revision` | To generate a database migration revision. |

## Usage Patterns

### Standard Development Flow
1. **Initialize**: `./script/bootstrap`
2. **Implement**: Make your changes to the code.
3. **Database**: If you changed models, run `./script/db_revision "..."`.
4. **Lint**: `./script/lint` to check for style issues.
5. **Test**: `./script/test` to run the test suite.
6. **Verify**: `./script/server` to run an ephemeral server for manual checks.

### Inner-Loop vs Pre-PR Verification
- **Fast Python inner loop (`<2s`, during edits)**: Target only the modified files and matching test modules:
  ```bash
  uv run --no-sync ruff check --fix <changed_files> && uv run --no-sync ruff format <changed_files> && uv run --no-sync pytest <target_test_files> -q
  ```
- **Fast Frontend inner loop (`<1s`, during `supernote/server/static/` or `tests/frontend/` edits)**:
  ```bash
  node --import ./tests/frontend/helpers/register_vue_stub.mjs --test 'tests/frontend/**/*.test.mjs'
  ```
- **Pre-PR gate (once per slice before commit/push)**:
  1. **Adversarial self-review by default**: Run a brief two-pass review on `git diff origin/main` before opening the PR—Pass 1 (Invariants & Boundaries: multi-user `user_id` scoping, lifecycle/delete semantics, generalization over parallel ad-hoc paths, `testing-style.md` typed clients/`load_components`) and Pass 2 (Subtractive / Anti-Fluff: delete dead wrappers, magic sentinels, and scope creep). Also check whether backend behavior changes require updating end-user docs or Web UI copy.
  2. **Full lint & test verification**: Run `(./script/lint || ./script/lint) && ./script/test` (the first `./script/lint` run lets `biome check --write` / `ruff` auto-format modified files; the second confirms zero remaining issues across `supernote/`, `tests/`, and `script/`). When changes touch component defaults/dependencies or `/api/extended/system/*` auth, also run `uv run --no-sync pytest tests/integration/test_web_ui.py tests/integration/test_live_server.py -q`.
  3. **Watch CI after push**: Run `sleep 3 && gh pr checks --watch <pr_number>` so new workflow runs register and any CI failure is caught proactively.
- **Direct `uv run` & Worktree Notes**: Always include `--no-sync` on ad-hoc `uv run` commands so `requirements_dev.txt` packages remain installed; batch independent `read_file` calls in parallel; in secondary git worktrees where `main` is checked out elsewhere, `gh pr merge <pr_number> --squash` merges the PR on GitHub before exiting non-zero on local `git checkout main`—follow with `git fetch origin main` and switch off `origin/main`.

### Notes
- All scripts are located in the `script/` directory at the project root.
- Scripts are designed to be run from the project root.
- The scripts will automatically use `uv` if it is installed, otherwise they will fall back to standard Python tools.

## Visual UI Testing Flow

When iterating on or verifying any Web UI feature (`supernote/server/static/` and supporting `supernote/server/routes/` endpoints), activate the `server-ui` skill ([`../server-ui/SKILL.md`](../server-ui/SKILL.md)) for frontend conventions, testing guardrails, and headless Playwright screenshot capture against an in-process ephemeral server.
