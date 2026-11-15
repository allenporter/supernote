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
- **Fast inner loop (`<2s`, during edits)**: Target only the modified files and matching test modules:
  ```bash
  uv run --no-sync ruff check --fix <changed_files> && uv run --no-sync ruff format <changed_files> && uv run --no-sync pytest <target_test_files> -q
  ```
- **Pre-PR gate (once per slice before commit/push)**: Run `./script/lint && ./script/test`.
- **Direct `uv run` & CI checks**: Always include `--no-sync` on ad-hoc `uv run` commands so `requirements_dev.txt` packages remain installed; batch independent `read_file` calls in parallel; watch GitHub Actions with a single backgrounded `gh pr checks <pr_number> --watch` (`WaitMsBeforeAsync: 500`) rather than polling loops.

### Notes
- All scripts are located in the `script/` directory at the project root.
- Scripts are designed to be run from the project root.
- The scripts will automatically use `uv` if it is installed, otherwise they will fall back to standard Python tools.

## Visual UI Testing Flow

When iterating on or verifying any Web UI feature (`supernote/server/static/` and supporting `supernote/server/routes/` endpoints), activate the `server-ui` skill ([`../server-ui/SKILL.md`](../server-ui/SKILL.md)) for frontend conventions, testing guardrails, and headless Playwright screenshot capture against an in-process ephemeral server.
