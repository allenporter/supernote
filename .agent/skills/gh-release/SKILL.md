---
name: gh-release
description: End-to-end release preparation, QA verification, curated release notes authoring, version bumping in pyproject.toml, and GitHub release publishing. Use when preparing QA, drafting release notes, or cutting a new version of the project.
---

# GitHub Release Skill

End-to-end workflow for preparing, verifying, documenting, and publishing a release of `supernote`.

## Semantic Versioning (SemVer)

This project follows [Semantic Versioning](https://semver.org/):

- **MAJOR** (`X.0.0`): Incompatible API, CLI, or schema/config changes.
- **MINOR** (`0.X.0`): Backward-compatible new features or capabilities.
- **PATCH** (`0.0.X`): Backward-compatible bug fixes or security patches.

## Release Workflow (Three Phases)

### Phase 1: Release QA

Run the verification checklist in [`references/qa-checklist.md`](references/qa-checklist.md) against the target `origin/main` commit before cutting a release:

1. **Automated gates**: `./script/lint`, `./script/test`, `./script/docs`, and green CI on `origin/main`.
2. **Database upgrade & migration safety**: fresh install + upgrade from previous release tag (`<prev-tag>` → `HEAD`) when `supernote/alembic/versions/` changed, plus `alembic check`.
3. **Zero-AI / optionality & config compatibility**: server boots with bare default config and with previous-release `config.yaml` / env vars.
4. **End-to-end smoke of headline changes**: real ephemeral server + Playwright UI verification (via the `server-ui` skill) for Web UI changes, plus CLI and MCP spot-checks.
5. **Packaging & distribution sanity**: `python3 -m build` wheel/sdist contents and clean-venv install smoke, plus Docker build verification.
6. **Release hygiene**: SemVer decision, security/breaking-change audit, and doc parity check.

Fix any blocking issues via PRs to `main` before proceeding.

### Phase 2: Curated Release Notes

Draft release notes following [`references/release-notes-guide.md`](references/release-notes-guide.md) and the voice/accuracy principles in `.agent/rules/documentation-style.md`:

- Review `git log <prev-tag>..origin/main` and merged PRs to identify user-facing outcomes (filtering out internal refactors, test-only work, and routine dependency bumps).
- Group by user-facing area, keep it scannable in <30 seconds, mark opt-in vs. default capabilities, and always include a **Breaking Changes & Upgrade Notes** section (listing automatic Alembic migration IDs and any config/event/API changes).
- Verify every referenced CLI flag, config key, MCP tool, URL hash, and migration ID against `origin/main`.
- Credit external contributors and end with the GitHub `Full Changelog` compare link.

### Phase 3: Cut & Publish Release

Once QA passes and the curated release notes are approved, run `create-release.sh` from the repository root on `main`:

```bash
# Preferred: publish with curated release notes
.agent/skills/gh-release/scripts/create-release.sh 0.28.0 --notes-file /path/to/release-notes.md

# Fallback: auto-generated notes via .github/release.yml
.agent/skills/gh-release/scripts/create-release.sh 0.28.0
```

`create-release.sh` will:
1. Verify clean working tree, `main` branch, `gh` CLI availability, and (if given) `--notes-file` existence.
2. Update `version` in `pyproject.toml` (and `uv.lock` if present).
3. Commit `chore(release): <version>` and push to `main`.
4. Create the GitHub release via `gh release create "<version>"` (triggers `.github/workflows/publish.yaml` for PyPI and `.github/workflows/docker.yaml` for GHCR).

After publishing, verify the PyPI and Docker release workflows succeed on GitHub Actions.

## Requirements

- `gh` CLI installed and authenticated (`gh auth status`).
- Run `create-release.sh` from the repository root on an up-to-date, clean `main` branch.

## Resources

- [`references/qa-checklist.md`](references/qa-checklist.md) — Release QA verification checklist and pass criteria.
- [`references/release-notes-guide.md`](references/release-notes-guide.md) — Structure, voice, and checklist for curated release notes.
- [`scripts/create-release.sh`](scripts/create-release.sh) — Version bump, commit, push, and GitHub release creation script.
