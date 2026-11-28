---
trigger: glob
globs: "**/docs/**, **/README.md, **/script/build_docs.py"
description: Altitude model, voice, and grading rubric for user and architecture documentation.
---

# Documentation Authoring & Review Principles

When authoring, restructuring, or reviewing documentation across `README.md`, `docs/`, and `script/build_docs.py`, apply these principles, altitude boundaries, and grading criteria.

---

## 1. Altitude Model (Assign Every File to Exactly One Altitude)

Most documentation confusion comes from **altitude mixing** (e.g., jumping from "Sync your Supernote in 3 steps" into internal class names and IR metrics on the same page). Every document belongs to one altitude:

| Altitude | Directory / Files | Audience | Speaks In… | Never Includes… |
| :--- | :--- | :--- | :--- | :--- |
| **30,000 ft — Orientation** | `README.md` (~150–200 lines) | First-time visitor (e.g., r/Supernote) | Outcomes, footprint (~135 MB), modularity ladder, screenshots, minimal quick start | Internal Python classes, SQL tables, raw benchmark matrices, full policy tables |
| **10,000 ft — Capabilities & Workflows** | `docs/guides/*.md` | Supernote owner / self-hoster | User concepts (notebooks, sketches, Obsidian, Apple Reminders, Gemini vs. Ollama) & minimal config snippets | Full YAML schema dumps, wire byte layouts, internal service/worker architecture |
| **1,000 ft — Reference** | `docs/reference/*.md`, `evals/*/RESULTS.md`, `api-spec/` | Operator / power user / integrator | Exact YAML keys, CLI flags, MCP parameters, full benchmark tables | Long onboarding essays or marketing prose |
| **Ground Level — Architecture** | `docs/architecture/*.md`, `docs/architecture/adr/*.md`, `pdoc` API | Contributor / plugin author | `ServerCore`, vertical components (`supernote.server.components.*`), DB models, wire protocol, ADRs | End-user installation tutorials |

*(Keep `docs/CONTRIBUTING.md` at `docs/CONTRIBUTING.md` so GitHub auto-detects it.)*

**Golden Altitude Rule:** A document may **link down** one altitude (e.g., a 10,000 ft guide linking to `docs/reference/configuration.md` or `evals/ocr/RESULTS.md`), but never **inline** lower-altitude detail that belongs on another page.

---

## 2. Core Documentation Principles

1. **Lead with Modularity & Low Footprint ("Everything Is Optional")**:
   - Make clear what works with **zero AI** and **zero optional modules** (~135 MB bare sync, SQLite, lazy-loaded vertical components where disabled features are never imported).
   - Never present optional capabilities (AI OCR, embeddings, LLM Wiki, MCP, webhooks) as prerequisites for running Private Cloud.

2. **User-Facing Capability Guides ≠ 1:1 Code Component Docs**:
   - Organize `docs/guides/` around what users accomplish (e.g., AI Providers, OCR & Multimodal, Search, LLM Wiki, MCP & Agents, Tasks & Integrations, Offline `.note` Toolkit) with a consistent flow: *What it unlocks → How to enable (opt-in vs. default) → Everyday workflow → Configuration & CLI/MCP pointers*.
   - Keep the 1:1 **Server Component Catalog** (mapping every `supernote.server.components.<domain>` to defaults, dependencies, and platforms) at Ground Level for contributors.

3. **Frame AI Provider Choices by Concrete Tradeoffs, Not Ideology**:
   - Present a neutral three-way choice: **Best Quality & Speed (Google Gemini)** · **100% Local / Self-Hosted (Ollama, vLLM, llama.cpp, Apple Vision fallback)** · **Sync Only (No AI)**.
   - Anchor recommendations in verified project benchmarks (`evals/ocr/RESULTS.md`, `evals/search/RESULTS.md`): state clearly that Gemini is the highest-accuracy, fastest default while respecting users who prefer local-only inference and being transparent about quality tradeoffs.
   - State API data-use facts plainly without loaded framing (e.g., Gemini Paid tier does not train on API data; Free tier does; local models never leave the network).

4. **One Topic Per Guide & Single Source of Truth**:
   - Give each document one clear audience and scope; split guides when they accumulate unrelated concerns.
   - Keep full config schemas in `docs/reference/configuration.md`, raw eval tables in `evals/*/RESULTS.md`, and internal design rationale in `docs/architecture/adr/`—link to them from user guides instead of copy-pasting tables that drift.

5. **Grounded in Verified Code & Synced with `script/build_docs.py`**:
   - Verify every documented flag, config key, MCP tool, component name, and benchmark number against the current codebase before publishing.
   - Register every new user or architecture guide in `GUIDE_SPECS` in `script/build_docs.py`, use relative repository links (never `file://` URIs), and verify `./script/docs` builds cleanly.

6. **Friendly, Human Voice (Avoid AI Writing Tells)**:
   - Write like a helpful maintainer explaining the project to another Supernote owner: use second person ("you"), present tense, active voice, and varied sentence lengths.
   - **Avoid bold-prefix bullet lists** (`- **Catchy Label**: One sentence...`) for feature prose. Use short paragraphs, plain unbolded bullets, or `###` subheadings instead (reserve bold lead-ins for true key-value or parameter lists).
   - **Avoid SaaS buzzwords and filler**: cut words and headings like *"What It Unlocks"*, *"Human-First"*, *"Living Knowledge Base"*, *"seamless"*, *"effortlessly"*, *"robust"*, *"complete with..."*, *"simply"*, and *"just"*.
   - **Use em dashes (`—`) sparingly**: prefer periods, commas, or parentheses.
   - **Keep internal names out of introductory prose**: explain behavior in plain English and only name internal enum values or config keys where the reader actually needs them.
   - Describe what the system does today on its own merits—never frame user docs comparatively against rejected drafts, past refactors, or PR history.

---

## 3. Grading Rubric (0–10 Scale)

Score each document `0` (Fail), `1` (Partial), or `2` (Pass) across five criteria:

1. **Altitude Fit (0–2)**: Stays strictly at its assigned altitude; links down instead of inlining lower-level jargon or tables.
2. **Time-to-First-Answer (0–2)**: Target persona can answer their #1 question in <30 seconds by scanning headings and tables.
3. **Optionality & Honest Tradeoffs (0–2)**: Default vs. opt-in is unambiguous; zero-AI baseline is clear; cloud vs. local tradeoffs are factual and benchmark-backed.
4. **Single Source of Truth (0–2)**: One topic per page; links to canonical references without duplicating tables that drift.
5. **Code & Build Accuracy (0–2)**: Every flag, config key, MCP tool, component, and link is verified against `main` and `./script/docs` succeeds.

*Target bar:* **9–10** to ship; any **0** blocks merge.
