---
name: backlog
description: Triage GitHub issues, apply the project label taxonomy and prioritization rubric, and select the highest-priority agent-ready tasks to implement.
---

# Backlog Triage & Prioritization Skill

Use this skill when triaging GitHub issues/PRs, proposing roadmap priorities, or selecting the next issue to work on autonomously.

## 1. Source of Truth

**GitHub Issues + Labels** are the single operational source of truth for live backlog status, priority, and agent readiness. `ROADMAP.md` holds high-level strategic phases and prioritization principles rather than per-issue checkboxes.

## 2. Label Taxonomy (4 Orthogonal Dimensions)

Every open engineering issue (excluding Renovate's Dependency Dashboard `#1`) should have **exactly 1 Type**, **exactly 1 Priority**, **1–3 Area labels**, and an optional **Agent Readiness** label:

### A. Priority (`p1`, `p2`, `p3`) — Mutually Exclusive
Apply this prioritization rubric from highest to lowest:
1. **`p1` (High / Next Up)**:
   - Data safety, sync integrity, security/auth correctness, or user-visible regressions (`bug` + `security` / `storage-sync`).
   - Small, high-leverage unblockers for active in-flight features or multi-provider architecture.
2. **`p2` (Medium / Planned)**:
   - Well-aligned roadmap features across Notebook parsing/rendering, AI OCR/search/synthesis, Web UI workflows, MCP tools, Schedule/Tasks, and developer test infrastructure.
3. **`p3` (Low / Icebox)**:
   - Large-surface protocol servers or long-horizon extensions (e.g., full CalDAV/WebDAV servers, multi-notebook RAG chat) until higher-priority core workflows settle.

### B. Agent Readiness (`agent-ready`, `needs-design`) — Mutually Exclusive
- **`agent-ready`**: Problem statement, architectural boundaries, and acceptance criteria are clear enough for a coding agent (or contributor) to implement end-to-end and open a PR without further product/design ambiguity.
- **`needs-design`**: Has open architectural tradeoffs, schema questions, or UX scope choices. Agents **must not** jump straight into coding a `needs-design` issue unless explicitly asked—instead, research options, propose a design on the issue or in chat, and align with the maintainer first.

### C. Type (`bug`, `enhancement`, `tech-debt`, `documentation`, `dependencies`) — Mutually Exclusive on Issues
- **`bug`**: Broken behavior, data loss, spec non-compliance, or regression. *(Never combine `bug` + `enhancement` on the same issue.)*
- **`enhancement`**: User-facing feature or API capability.
- **`tech-debt`**: Internal refactoring, performance optimization, static typing, CI, or test harness improvements.
- **`documentation`**: Docs, guides, recipes, and architecture specs.
- **`dependencies`**: Automated dependency updates (Renovate).

### D. Area (`ai`, `web-ui`, `mcp`, `notebook`, `security`, `storage-sync`, `schedule`, `cli-client`)
- `ai`: OCR, summarization, embeddings, prompts, vocabulary, and AI model providers.
- `web-ui`: Built-in SPA (`supernote/server/static/`) and frontend UX.
- `mcp`: Model Context Protocol server, OAuth consent/tokens, tools, resources, and prompts.
- `notebook`: `.note`, `.mark`, and `.spd` parser, decoder, manipulator, and PDF/PNG/SVG converters.
- `security`: Authentication, rate limiting, token/session security, quotas, and data protection.
- `storage-sync`: VFS, `BlobStorage`, device/web sync routes, and extended sync APIs.
- `schedule`: To-Do tasks, task groups, recurring tasks, `.ics` feeds, and CalDAV.
- `cli-client`: `supernote` CLI commands and `supernote.client` Python SDK.

*(Note: Pull Requests are automatically labeled by file path and branch prefix via `.github/labeler.yml`.)*

## 3. Standard `gh` Queries for Agents

```bash
# 1. Pick the next highest-priority autonomous task
gh issue list --state open --label "p1" --label "agent-ready" --json number,title,labels

# 2. Fall back to p2 agent-ready tasks (optionally filtered by area, e.g. --label "notebook")
gh issue list --state open --label "p2" --label "agent-ready" --json number,title,labels

# 3. Find issues needing triage (missing priority p1/p2/p3)
gh issue list --state open --limit 100 --json number,title,labels \
  --jq '.[] | select(.number != 1) | select(([.labels[].name] | inside(["p1","p2","p3"]) | not) and (([.labels[].name] | any(. == "p1" or . == "p2" or . == "p3")) | not))'

# 4. Review open design discussions
gh issue list --state open --label "needs-design" --json number,title,labels
```

## 4. Triage Checklist When Creating or Reviewing Issues

1. Ensure the title uses Conventional Commit style where natural (`feat(area): ...`, `fix(area): ...`, `refactor(area): ...`, `test(area): ...`).
2. Include a concise `## Summary` and checkable `## Goals` acceptance criteria.
3. Assign **1 Type** + **1 Priority (`p1`/`p2`/`p3`)** + **1–3 Area labels** + **`agent-ready` or `needs-design`**.
4. Check open PRs (`gh pr list --state open`) before picking up an `agent-ready` issue so you do not duplicate in-flight work.
