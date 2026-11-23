---
name: code-review-style
description: Prescriptive step-by-step workflow for reviewing code diffs, pull requests, and API changes against core engineering principles and architectural standards.
---

# Code Review Workflow Skill

Execute this prescriptive task list when reviewing code changes, auditing PRs, or validating refactored codebase components. For detailed design rationale and examples, refer to [docs/code_review_style.md](../../../docs/code_review_style.md).

---

## Task Checklist & Step-by-Step Execution

### Step 1: Verify 1:1 Test Parity & Relative Links
- [ ] Verify that every implementation file has a corresponding test file matching its exact module name.
  - *Python rule*: `supernote/path/to/module.py` $\rightarrow$ `tests/path/to/test_module.py`.
  - *Frontend JS rule*: `supernote/server/static/js/{api,composables,utils}/<module>.js` $\rightarrow$ `tests/frontend/<module>.test.mjs` (plus `components.test.mjs` & `tests/integration/test_web_ui.py`).
- [ ] Ensure all committed markdown files and skill definitions use relative repository paths instead of `file://` URIs.

### Step 2: Audit Abstraction Boundaries (Zero Leaky Abstractions)
- [ ] Inspect API method signatures: verify high-level methods use domain models and standard exception semantics (`None` on success, typed exceptions on failure; in frontend JS, subclass `Error` via `ApiError extends Error` rather than `Object.assign(new Error(...), { status })`, and unwrap wire envelopes inside `api/client.js` & `api/schedule.js` rather than inside Vue components).
- [ ] Confirm no transport tokens, wire literals (e.g. `"Received"`, `"true"`), or status strings leak to upper layers.
- [ ] Audit role cohesion: verify interfaces do not leak caller concerns (storage, scheduling, query building) downward into implementations, and prefer declarative properties over bespoke per-subclass hooks.
- [ ] Check exception blocks: ensure broad `except Exception:` is replaced with narrow parse errors (`(json.JSONDecodeError, ValueError, TypeError, KeyError)`).

### Step 3: Audit Orthogonality & State Isolation
- [ ] Verify control operations (pings, health checks) do not share queue state with application data streams.
- [ ] Confirm explicit dependency injection: ensure config and service dependencies are passed explicitly via parameters rather than extracted from `app["config"]` or global dictionaries.

### Step 4: Audit Defensive API Ergonomics
- [ ] Verify there is one canonical way to perform each operation (no redundant wrapper methods).
- [ ] Check return type annotations for determinism (no ambiguous union return types like `str | DomainModel`).
- [ ] Confirm event streams use standard Python async iterators (`async for msg in client.messages():`).

### Step 5: Audit Linear Control Flow & Guard Clauses
- [ ] Check for early returns and guard clauses to keep main happy paths unindented (avoid pre-declaring dummy locals like `x = y or 0` or `None`/`[]` placeholders that an up-front guard clause eliminates).
- [ ] Verify repetitive error emission or formatting blocks are extracted into flat helper methods.
- [ ] Check code hygiene: top-level imports only, no numbered comments (`# 1.`, `# 2.`), and minimal `__all__` exports exposing only true public API symbols (do not re-export internal helpers).
- [ ] Verify `pdoc`-compatible inline attribute docstrings (`"""..."""` placed directly beneath dataclass/schema fields rather than `Attributes:` class-docstring blocks) and rationale comments explaining *why* non-obvious DB columns, indexes, constraints, or helper methods exist.
- [ ] Audit minimalism & PR size: run `git diff --stat origin/main`, verify built-in library primitives are used instead of custom wrapper classes/validators, reuse existing domain helpers in Alembic data migrations (extending existing migration DB test fixtures with a minimal delta), and flag diffs exceeding ~300–400 production LoC for splitting.

### Step 6: Audit Test Quality & Fixture Delegation
- [ ] Verify one behavior/scenario per `test_*` method (split multi-scenario mega-tests into separate test methods or `@pytest.mark.parametrize`).
- [ ] Verify assertions check full dictionary structures (`assert data_dict == {...}`).
- [ ] Ensure test setup boilerplate is delegated to reusable fixtures (`socket_client`, `create_socket_client`), preferring real fakes/fixtures and explicit DI; when mocking is unavoidable, use `unittest.mock.patch` rather than pytest `monkeypatch`.
- [ ] Reject structural meta-tests (never write tests asserting `__all__` exports, AST/docstring formatting, or substring checks against Python/JS/HTML source files).
- [ ] In frontend `node:test` suites (`tests/frontend/*.test.mjs`), use `t.mock.timers.enable({ apis: ['setTimeout'] })` and `mountComposable()` (`tests/frontend/helpers/vue_test_scope.mjs`) instead of wall-clock `setTimeout` sleeps, and verify zero dropped assertions when splitting or refactoring test files.
- [ ] When executing multi-slice PR plans, run a fresh-context `research` subagent review against `origin/main...HEAD` before merging each slice.
- [ ] Run linters & type checks: `./script/lint` (covers `ruff`, `ty`, `tsc --noEmit`, `biome check`, `codespell`, `yamllint`).
- [ ] Run test suites: `uv run --no-sync pytest --cov=supernote --cov-report=term-missing` (and `node --import ./tests/frontend/helpers/register_vue_stub.mjs --test 'tests/frontend/**/*.test.mjs'` when frontend files change).

---

## Backend Hostile / Adversarial Review Rubric (Two Passes)

Whenever asked for a hostile/adversarial review on Python/backend changes, run both passes (when changes touch Web UI assets, also run the 7-point rubric in [`../server-ui/references/ui-review-and-testing.md`](../server-ui/references/ui-review-and-testing.md)):

1. **Pass 1 — Invariants & Boundaries**: Audit multi-tenant `user_id` PK and query scoping, DB transaction and per-file lock races, wire-protocol and DTO compatibility, and narrow exception types.
2. **Pass 2 — Subtractive / Anti-Fluff (Required After Every Review Round)**: Run `git diff --stat origin/main` and actively look for code to delete—remove single-caller wrapper classes/factories and optional parameters, replace magic string sentinels (`"0"`, `""`) with `None`, strip speculative runtime `isinstance`/reentrancy guards for impossible internal states, and revert scope creep into unrelated modules.

---

## Execution Protocol

1. **Map Diffs**: Identify changed implementation and test modules via `git diff --name-only` and check diff budget via `git diff --stat origin/main`.
2. **Run Linter & Tests**: Execute `uv run --no-sync ruff check .` and `uv run --no-sync pytest --cov=supernote --cov-report=term-missing`.
3. **Audit Diffs**: Inspect Python changes against Steps 1–6 checklist items and the two-pass backend adversarial rubric. Whenever diffs touch Web UI assets (`supernote/server/static/` or supporting UI routes), also activate [`../server-ui/SKILL.md`](../server-ui/SKILL.md) and audit against the 7-point rubric and Playwright E2E/mobile checks in [`../server-ui/references/ui-review-and-testing.md`](../server-ui/references/ui-review-and-testing.md).
4. **Format Output**: Synthesize review results using the audit report template below. When drafting comments for external PRs, explain the underlying problem first, state one clear recommendation (avoid hedging with unwanted options like per-model heuristics), and anchor architectural feedback to the contributor's concrete use case.

---

## Structured Review Output Template

```markdown
### Code Review Audit Report

| Engineering Principle / Area | Status | Audit Findings |
| :--- | :---: | :--- |
| **1:1 Test Parity & Links** | PASS / FAIL | ... |
| **Abstraction Boundaries** | PASS / FAIL | ... |
| **State Isolation & DI** | PASS / FAIL | ... |
| **Defensive API Ergonomics** | PASS / FAIL | ... |
| **Linear Control Flow** | PASS / FAIL | ... |
| **Test Quality & Coverage** | PASS / FAIL | ... |

**Coverage Summary**:
- Target Subsystem Coverage: X%
- Unit & Integration Test Results: N passed, 0 failed

**Actionable Recommendations**:
1. ...
```
