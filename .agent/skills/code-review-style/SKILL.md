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
- [ ] Check code hygiene: top-level imports only, no numbered comments (`# 1.`, `# 2.`), and clean `__all__` package exports.

### Step 6: Audit Test Quality & Fixture Delegation
- [ ] Verify assertions check full dictionary structures (`assert data_dict == {...}`).
- [ ] Ensure test setup boilerplate is delegated to reusable fixtures (`socket_client`, `create_socket_client`).
- [ ] Run linter: `uv run ruff check --fix . && uv run ruff format .`.
- [ ] Run test suite with coverage: `uv run pytest --cov=supernote --cov-report=term-missing`.

---

## Execution Protocol

1. **Map Diffs**: Identify changed implementation and test modules via `git diff --name-only`.
2. **Run Linter & Tests**: Execute `uv run ruff check .` and `uv run pytest --cov=supernote --cov-report=term-missing`.
3. **Audit Diffs**: Inspect changes against Steps 1–6 checklist items.
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
