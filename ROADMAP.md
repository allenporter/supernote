# Project Roadmap & Prioritization Strategy

This document outlines the strategic direction and prioritization rubric for **Open Private Cloud for Supernote**.

> **Live Execution Queue**: Individual features, bugs, and refactors are tracked directly in **[GitHub Issues](https://github.com/allenporter/supernote/issues)** and **[Strategic Milestones](https://github.com/allenporter/supernote/milestones)** rather than static checkboxes here so status never drifts when PRs merge:
> - 🔥 **[P1 — Next Up & Critical](https://github.com/allenporter/supernote/issues?q=is%3Aopen+is%3Aissue+label%3Ap1)** *(Data safety, correctness bugs, active focus)*
> - 🤖 **[Agent-Ready Queue (`p1` + `agent-ready`)](https://github.com/allenporter/supernote/issues?q=is%3Aopen+is%3Aissue+label%3Ap1+label%3Aagent-ready)** *(Well-scoped tasks ready to pick up)*
> - ✨ **[Quick Polish Wins (`polish` + `agent-ready`)](https://github.com/allenporter/supernote/issues?q=is%3Aopen+is%3Aissue+label%3Apolish+label%3Aagent-ready)** *(Single-PR <200 LoC UX, API, and reliability seams)*
> - 📋 **[P2 — Planned Roadmap](https://github.com/allenporter/supernote/issues?q=is%3Aopen+is%3Aissue+label%3Ap2)** *(Core feature & quality backlog)*
> - 🧭 **[Needs Design (`needs-design`)](https://github.com/allenporter/supernote/issues?q=is%3Aopen+is%3Aissue+label%3Aneeds-design)** *(Open architectural proposals)*
> - 🧊 **[P3 — Icebox / Long-Horizon](https://github.com/allenporter/supernote/milestone/5)** *(Larger protocol extensions & future bets)*

---

## Prioritization Rubric

When triaging issues or choosing what to build next, we prioritize in this order:

1. **Data Safety, Security & Sync Trust (`p1`)**: Never lose, corrupt, or leak user notes. Soft-delete recovery, overwrite protection, strict per-user isolation, account-deletion cleanup, and auth/token hardening always come first.
2. **Device Protocol & `.note` Format Fidelity (`p1`–`p2`)**: Maintain 100% compatibility with physical Supernote firmware (including Chauvet `3.31+` plugins/transforms), native `.note` structures (`FILE_ID`, `TITLESTYLE`/`TITLEBITMAP`, `Link`s, `Keywords`), and `api-spec/openapi.yaml`.
3. **High-Leverage Daily UX & AI Quality (`p1`–`p2`)**: Fast, low-memory Web UI browsing, accurate OCR (device keyword vocabulary, human edit preservation, blank-page skip), searchable vector PDF exports, and cost-efficient local/cloud AI providers.
4. **Open PKM & Agent Ecosystem (`p2`)**: Composable primitives (MCP tools/OAuth, scoped App Tokens, incremental sync cursors, Digest exports) that let companion apps like Obsidian, Home Assistant, Readwise, and iOS/macOS viewers integrate cleanly without coupling server internals to external schemas.
5. **Long-Horizon Protocol Extensions (`p3`)**: Full standalone protocol surfaces (e.g., two-way CalDAV, WebDAV, multi-notebook RAG chat) once core storage, structure, and sync primitives are rock-solid.

---

## Strategic Phases

### Phase 1: Operational Readiness ("Daily Driver") — ✅ Complete
Secure, lightweight single-container deployment (~135–160MB idle RAM) with SQLite, reverse-proxy TLS docs, official Supernote Web UI & device protocol compatibility, rate limiting, and token redaction across logs.

### Phase 2: Safety & Integrity ("Trustworthy Storage") — 🔄 Active Hardening ([Milestone #1](https://github.com/allenporter/supernote/milestone/1))
- **Completed**: Per-user storage isolation, content-addressed `BlobStorage` with opportunistic TTL temp/chunk cleanup, typed hash/password models, and backend Recycle Bin soft-delete (`RecycleFileDO`).
- **Focus Areas** ([`storage-sync`](https://github.com/allenporter/supernote/labels/storage-sync), [`security`](https://github.com/allenporter/supernote/labels/security)):
  - Web UI Recycle Bin recovery view, full artifact purge on account deletion, bounded file version history to protect against multi-device overwrite accidents, and automated OpenAPI/trace conformance checks.

### Phase 3: Notebook Structure, Web UI & Document Workflows — 🔄 Active Focus ([Milestone #2](https://github.com/allenporter/supernote/milestone/2))
- **Completed**: `supernote cloud` CLI operations, Prometheus metrics & trace logging, strict-typed modular Vue 3 Web UI, scroll-synced per-page OCR transcripts, lazy cover thumbnails, notebook page deep-linking, and native `.note` metadata persistence (`FILE_ID`, per-page keywords, and outgoing cross-note links).
- **Focus Areas** ([`notebook`](https://github.com/allenporter/supernote/labels/notebook), [`web-ui`](https://github.com/allenporter/supernote/labels/web-ui)):
  - `TITLEBITMAP` heading OCR & `TITLESTYLE` hierarchy, incoming backlink discovery, native keyword search, searchable PDF export with TOC bookmarks, `.pdf.mark` sidecar rendering, and Chauvet `3.31+` compatibility.

### Phase 4: Intelligence & Human-in-the-Loop AI — 🔄 Active Focus ([Milestone #3](https://github.com/allenporter/supernote/milestone/3))
- **Completed**: Background OCR (with page-style prompt routing & page keyword hints), daily/notebook summarization, semantic vector search, and pluggable Gemini + local OpenAI-compatible (Ollama / llama.cpp / vLLM) providers.
- **Focus Areas** ([`ai`](https://github.com/allenporter/supernote/labels/ai)):
  - Incremental/chunked long-notebook summarization, shared `"AI Summaries"` Digest curation & Web UI Digests view, scoped OCR vocabulary harvested from device keywords, non-destructive human transcript edits (`user_text` vs `ocr_text`), handwritten Digest marginalia OCR, Vertex AI / Gemini Flex cost optimization, and Web UI prompt management.

### Phase 5: Companion Ecosystem, MCP & Schedule — 🔄 Active Focus ([Milestone #4](https://github.com/allenporter/supernote/milestone/4))
- **Completed**: Built-in MCP server with OAuth 2.1 + browser Consent Card, static scoped Bearer API keys (`sn_...`), unified cursor-based Domain Event Log (`GET /api/extended/events` + Socket.IO push), schedule task sync, and RFC 5545 `.ics` VTODO export.
- **Focus Areas** ([`mcp`](https://github.com/allenporter/supernote/labels/mcp), [`schedule`](https://github.com/allenporter/supernote/labels/schedule)):
  - Web UI API key & OAuth session management, MCP task/VFS/event tools & resources, global/per-notebook causal Activity UI, token-authenticated `.ics` feed URLs, recurring task overrides, and handwritten task reconciliation (with long-horizon protocol extensions tracked in [Milestone #5](https://github.com/allenporter/supernote/milestone/5)).
