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
  - *Rule*: `supernote/path/to/module.py` $\rightarrow$ `tests/path/to/test_module.py`.
- [ ] Ensure all committed markdown files and skill definitions use relative repository paths instead of `file://` URIs.

### Step 2: Audit Abstraction Boundaries (Zero Leaky Abstractions)
- [ ] Inspect API method signatures: verify high-level methods use domain models and standard exception semantics (`None` on success, typed exceptions on failure).
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
- [ ] Check for early returns and guard clauses to keep main happy paths unindented.
- [ ] Verify repetitive error emission or formatting blocks are extracted into flat helper methods.
- [ ] Check code hygiene: top-level imports only, no numbered comments (`# 1.`, `# 2.`), and minimal `__all__` exports exposing only true public API symbols (do not re-export internal helpers).
- [ ] Verify `pdoc`-compatible inline attribute docstrings (`"""..."""` placed directly beneath dataclass/schema fields rather than `Attributes:` class-docstring blocks) and rationale comments explaining *why* non-obvious DB columns, indexes, constraints, or helper methods exist.
- [ ] Audit minimalism & PR size: verify built-in library primitives are used instead of custom wrapper classes/validators, and flag diffs exceeding ~300–400 production LoC for splitting.

### Step 6: Audit Test Quality & Fixture Delegation
- [ ] Verify one behavior/scenario per `test_*` method (split multi-scenario mega-tests into separate test methods or `@pytest.mark.parametrize`).
- [ ] Verify assertions check full dictionary structures (`assert data_dict == {...}`).
- [ ] Ensure test setup boilerplate is delegated to reusable fixtures (`socket_client`, `create_socket_client`), preferring real fakes/fixtures and explicit DI; when mocking is unavoidable, use `unittest.mock.patch` rather than pytest `monkeypatch`.
- [ ] Reject structural meta-tests (never write tests asserting `__all__` exports, AST/docstring formatting, or substring checks against Python/JS/HTML source files).
- [ ] Run linter: `uv run --no-sync ruff check --fix . && uv run --no-sync ruff format .`.
- [ ] Run test suite with coverage: `uv run --no-sync pytest --cov=supernote --cov-report=term-missing`.

---

## Backend Hostile / Adversarial Review Rubric (Two Passes)

Whenever asked for a hostile/adversarial review on Python/backend changes, run both passes (when changes touch Web UI assets, also run the 7-point rubric in [`../server-ui/references/ui-review-and-testing.md`](../server-ui/references/ui-review-and-testing.md)):

1. **Pass 1 — Invariants & Boundaries**: Audit multi-tenant `user_id` PK and query scoping, DB transaction and per-file lock races, wire-protocol and DTO compatibility, and narrow exception types.
2. **Pass 2 — Subtractive / Anti-Fluff**: Remove single-caller wrapper classes, replace magic string sentinels (`"0"`, `""`) with `None`, and strip speculative guards for impossible internal states.

---

## Execution Protocol

1. **Map Diffs**: Identify changed implementation and test modules via `git diff --name-only`.
2. **Run Linter & Tests**: Execute `uv run --no-sync ruff check .` and `uv run --no-sync pytest --cov=supernote --cov-report=term-missing`.
3. **Audit Diffs**: Inspect Python changes against Steps 1–6 checklist items and the two-pass backend adversarial rubric. Whenever diffs touch Web UI assets (`supernote/server/static/` or supporting UI routes), also activate [`../server-ui/SKILL.md`](../server-ui/SKILL.md) and audit against the 7-point rubric and Playwright E2E/mobile checks in [`../server-ui/references/ui-review-and-testing.md`](../server-ui/references/ui-review-and-testing.md).
4. **Format Output**: Synthesize review results using the audit report template below.

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
