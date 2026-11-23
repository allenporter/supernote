---
name: backlog
description: Triage GitHub issues, apply the project label taxonomy and prioritization rubric, and select the highest-priority agent-ready tasks to implement.
---

# Backlog Triage & Prioritization Skill

Use this skill when triaging GitHub issues/PRs, proposing roadmap priorities, or selecting the next issue to work on autonomously.

## 1. Source of Truth

**GitHub Issues + Labels + Strategic Milestones** are the single operational source of truth for live backlog status, priority, strategic track, and agent readiness. `ROADMAP.md` holds high-level strategic phases and prioritization principles rather than per-issue checkboxes.

## 2. Strategic Milestones (Vertical Tracks)

Every open engineering issue (excluding Renovate's Dependency Dashboard `#1`) belongs to **exactly 1 GitHub Milestone** aligned with `ROADMAP.md`:

1. **`Trustworthy Storage & Sync Safety`** *(Phase 2)*: Recycle Bin recovery, account-deletion cleanup, version history, and protocol/route conformance.
2. **`Notebook Structure, Search & Document Workflows`** *(Phase 3)*: Native `.note` headings (`TITLEBITMAP`/`TITLESTYLE`), links/backlinks, keyword search, PDF/SVG/`.pdf.mark` exports, and Chauvet `3.31+` compatibility.
3. **`Scalable AI, Transcripts & Digests`** *(Phase 4)*: Multi-provider AI lifecycle, chunked summarization, human transcript edits, prompt management, and Digest curation.
4. **`MCP, Event Log, Schedule & Companion Ecosystem`** *(Phase 5)*: API key/OAuth UI, MCP tools/resources/prompts, Domain Event Log & Activity UI, recurring tasks, and companion sync.
5. **`Long-Horizon & Protocol Extensions`** *(Icebox / `p3`)*: Standalone protocol surfaces (CalDAV, WebDAV), Atelier (`.spd`), `/INBOX` converters, and multi-notebook RAG chat/rollups.

## 3. Label Taxonomy (4 Orthogonal Dimensions + Optional Modifiers)

Every open engineering issue (excluding `#1`) must have **exactly 1 Type**, **exactly 1 Priority**, **exactly 1 Agent Readiness**, and **1–3 Area labels**:

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

### E. Optional Modifiers (`polish`, `good first issue`)
- `polish`: Single-PR UX, API, or reliability polish (<~200 LoC) closing a high-value seam on an existing feature.
- `good first issue`: Self-contained task suitable for new contributors.

*(Note: Pull Requests are automatically labeled by file path and branch prefix via `.github/labeler.yml`.)*

## 4. Standard `gh` Queries for Agents

```bash
# 1. Pick the next highest-priority autonomous task
gh issue list --state open --label "p1" --label "agent-ready" --json number,title,labels,milestone

# 2. Pick a quick single-PR polish win
gh issue list --state open --label "polish" --label "agent-ready" --json number,title,labels,milestone

# 3. Pick agent-ready work within a specific Strategic Milestone
gh issue list --state open --milestone "Notebook Structure, Search & Document Workflows" --label "agent-ready" --json number,title,labels

# 4. Fall back to p2 agent-ready tasks (optionally filtered by area, e.g. --label "notebook")
gh issue list --state open --label "p2" --label "agent-ready" --json number,title,labels,milestone

# 5. Audit full taxonomy compliance (missing priority, readiness, type, area, or milestone)
gh issue list --state open --limit 100 --json number,title,labels,milestone \
  --jq '.[] | select(.number != 1) | select(.milestone == null or ([.labels[].name] | any(. == "p1" or . == "p2" or . == "p3") | not) or ([.labels[].name] | any(. == "agent-ready" or . == "needs-design") | not))'

# 6. Review open design discussions
gh issue list --state open --label "needs-design" --json number,title,labels,milestone
```

## 5. Triage Checklist When Creating or Reviewing Issues

1. Ensure the title uses Conventional Commit style where natural (`feat(area): ...`, `fix(area): ...`, `refactor(area): ...`, `test(area): ...`).
2. Include a concise `## Summary` and checkable `## Goals` acceptance criteria.
3. Assign **1 Strategic Milestone** + **1 Type** + **1 Priority (`p1`/`p2`/`p3`)** + **1 Readiness (`agent-ready` or `needs-design`)** + **1–3 Area labels** (+ optional `polish` for <~200 LoC single-PR seams).
4. Check open PRs (`gh pr list --state open`) before picking up an `agent-ready` issue so you do not duplicate in-flight work.
5. **Append comments instead of editing**: When updating an existing issue with new context or suggestions, add a new comment (`gh issue comment`) rather than editing the original issue body unless explicitly asked.
6. **No reverse-engineering specifics**: Never include device firmware or APK reverse-engineering details in public GitHub issues.
7. **Match detail to readiness**: For `needs-design` or un-designed feature issues, focus on high-level motivation, verified facts/observations, and open ideas rather than prescriptive step-by-step implementation plans.
