# Project Roadmap & Prioritization Strategy

This document outlines the strategic direction and prioritization rubric for **Supernote Private Cloud & Knowledge Hub**.

> **Live Execution Queue**: Individual features, bugs, and refactors are tracked directly in **[GitHub Issues](https://github.com/allenporter/supernote/issues)** rather than static checkboxes here so status never drifts when PRs merge:
> - 🔥 **[P1 — Next Up & Critical](https://github.com/allenporter/supernote/issues?q=is%3Aopen+is%3Aissue+label%3Ap1)** *(Data safety, correctness bugs, active focus)*
> - 🤖 **[Agent-Ready Queue (`p1` + `agent-ready`)](https://github.com/allenporter/supernote/issues?q=is%3Aopen+is%3Aissue+label%3Ap1+label%3Aagent-ready)** *(Well-scoped tasks ready to pick up)*
> - 📋 **[P2 — Planned Roadmap](https://github.com/allenporter/supernote/issues?q=is%3Aopen+is%3Aissue+label%3Ap2)** *(Core feature & quality backlog)*
> - 🧭 **[Needs Design (`needs-design`)](https://github.com/allenporter/supernote/issues?q=is%3Aopen+is%3Aissue+label%3Aneeds-design)** *(Open architectural proposals)*
> - 🧊 **[P3 — Icebox / Long-Horizon](https://github.com/allenporter/supernote/issues?q=is%3Aopen+is%3Aissue+label%3Ap3)** *(Larger protocol extensions & future bets)*

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

### Phase 2: Safety & Integrity ("Trustworthy Storage") — 🔄 Active Hardening
- **Completed**: Per-user storage isolation, content-addressed `BlobStorage` with opportunistic TTL temp/chunk cleanup, typed hash/password models, and backend Recycle Bin soft-delete (`RecycleFileDO`).
- **Focus Areas** ([`storage-sync`](https://github.com/allenporter/supernote/labels/storage-sync), [`security`](https://github.com/allenporter/supernote/labels/security)):
  - Web UI Recycle Bin recovery view, per-user storage quota enforcement, full artifact purge on account deletion, and bounded file version history to protect against multi-device overwrite accidents or NAS ransomware.

### Phase 3: Notebook Structure, Web UI & Document Workflows — 🔄 Active Focus
- **Completed**: `supernote cloud` CLI operations, Prometheus metrics & trace logging, scroll-synced per-page OCR transcripts, lazy cover thumbnails, and notebook page deep-linking.
- **Focus Areas** ([`notebook`](https://github.com/allenporter/supernote/labels/notebook), [`web-ui`](https://github.com/allenporter/supernote/labels/web-ui)):
  - Native `.note` structural persistence (`FILE_ID`, cross-note/page/web `Link`s, `TITLESTYLE` hierarchy, and `TITLEBITMAP` heading OCR), Web UI Metadata & Outline tab, searchable PDF export with TOC bookmarks, `.pdf.mark` & `.spd` format support, and Chauvet `3.31+` compatibility.

### Phase 4: Intelligence & Human-in-the-Loop AI — 🔄 Active Focus
- **Completed**: Background OCR, daily/notebook summarization, semantic vector search, and pluggable Gemini + local OpenAI-compatible (Ollama / llama.cpp / vLLM) providers.
- **Focus Areas** ([`ai`](https://github.com/allenporter/supernote/labels/ai)):
  - Scoped OCR vocabulary harvested from device keywords, non-destructive human transcript edits (`user_text` vs `ocr_text`), handwritten Digest marginalia OCR, multi-provider & Vertex AI / Gemini Flex cost optimization, and Web UI prompt management.

### Phase 5: Companion Ecosystem, MCP & Schedule — 📋 Planned
- **Completed**: Built-in MCP server with OAuth 2.1, schedule task sync, and RFC 5545 `.ics` VTODO export.
- **Focus Areas** ([`mcp`](https://github.com/allenporter/supernote/labels/mcp), [`schedule`](https://github.com/allenporter/supernote/labels/schedule)):
  - OAuth consent card & scoped Bearer App Tokens for headless MCP agents and companion apps, cursor-based incremental change feed (`/api/extended/sync/changes`) for two-way Obsidian/PKM sync, handwritten task extraction, recurring task overrides, `/INBOX` article delivery, and future CalDAV/WebDAV surfaces.
