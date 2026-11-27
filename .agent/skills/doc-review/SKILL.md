---
name: doc-review
description: Step-by-step workflow for grading, auditing, and reviewing documentation PRs against the project's altitude model, 5-point rubric, code parity checks, and 4-persona cold-read tests.
---

# Documentation Review & Grading Skill

Execute this workflow when reviewing documentation PRs, auditing existing guides, or checking whether new features are accurately and clearly represented. All rules and altitude definitions live in [`.agent/rules/documentation-style.md`](../../rules/documentation-style.md).

---

## Step-by-Step Execution Protocol

### Step 1: Map Scope & Assign Altitude
- [ ] Identify changed or target documentation files (`git diff --name-only origin/main` for PRs, or `README.md` + `docs/` for full audits).
- [ ] Classify each file into its single assigned altitude from [`.agent/rules/documentation-style.md`](../../rules/documentation-style.md):
  - **30,000 ft**: `README.md` (target ~150–200 lines)
  - **10,000 ft**: `docs/guides/*.md`
  - **1,000 ft**: `docs/reference/*.md`, `evals/*/RESULTS.md`, `api-spec/`
  - **Ground Level**: `docs/architecture/*.md`, `docs/architecture/adr/*.md` (keep `docs/CONTRIBUTING.md` at `docs/` root for GitHub auto-detection)
- [ ] Flag any **altitude violations**: internal Python classes, SQL tables, or raw IR metrics in 30k/10k docs; marketing essays in 1k references; or duplicated benchmark/config tables that should link down to their canonical source.
- [ ] Flag **AI writing tells**: bold-prefix bullet lists (`- **Catchy Label**: ...`) used for prose, SaaS buzzwords (*"What It Unlocks"*, *"seamless"*, *"effortlessly"*, *"human-first"*, *"robust"*, *"complete with..."*), clustered em dashes (`—`), or internal enum/class names leaked into introductory user prose. Rewrite into plain, conversational second-person prose.

### Step 2: Verify Code Parity & Build Health
- [ ] **Component parity**: Confirm every domain in `BUILTIN_COMPONENTS` (`supernote/server/components/__init__.py`) is accurately represented in the Server Component Catalog (default-enabled status, dependencies, platforms).
- [ ] **MCP tool parity**: Compare tools registered in `supernote/server/components/*/mcp.py` against the MCP guide so no tool (e.g., `get_page_image`, wiki tools, schedule tools) is missing or stale.
- [ ] **Config & CLI parity**: Verify any documented `config.yaml` keys, `SUPERNOTE_*` environment variables, and `supernote` CLI flags against `supernote/server/config.py`, component `config.py` modules, and `supernote/cli/`.
- [ ] **Link & site build**: Confirm all committed markdown files use relative repository paths (never `file://` URIs), verify new guides are registered in `GUIDE_SPECS` inside `script/build_docs.py`, and run `./script/docs` (plus `./script/lint` for `codespell`).

### Step 3: Run the 4-Persona Cold-Read Test
For landing-page or multi-guide reviews, evaluate the docs strictly from what is written (prefer a fresh-context `research` subagent for major restructures) across four user personas:

1. **r/Supernote Pi/NAS Sync-Only User**: *"I want to replace Ratta's 2 GB stack on a Raspberry Pi with zero AI. How much RAM does it take, is AI optional, and what exact commands do I run?"*
2. **Local-First / Ollama User**: *"I want OCR and search without sending notes to the cloud. Which local models should I run, how do I configure them, and what quality tradeoff am I making?"*
3. **AI Power User (Multimodal + Wiki + MCP)**: *"I sketch diagrams and Bullet Journals and use Claude + Obsidian. How do OCR, hybrid search, `get_page_image`, and LLM Wiki work together?"*
4. **Developer / Plugin Author**: *"How do I parse/author `.note` files in Python, or add a new vertical server component?"*

Record click depth, unanswered questions, and jargon friction for each persona.

### Step 4: Score Against the 5-Point Rubric (0–10)
Grade each document `0` (Fail), `1` (Partial), or `2` (Pass) on:
1. **Altitude Fit (0–2)**
2. **Time-to-First-Answer (0–2)**
3. **Optionality & Honest Tradeoffs (0–2)**
4. **Single Source of Truth (0–2)**
5. **Code & Build Accuracy (0–2)**

*Ship bar:* **9–10** overall with **no `0` scores**.

---

## Structured Grading Report Template

```markdown
### Documentation Audit Report

| File | Assigned Altitude | Altitude Fit | Time-to-Answer | Optionality & Tradeoffs | Single Source | Code & Build | Total |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `README.md` | 30,000 ft | X/2 | X/2 | X/2 | X/2 | X/2 | **X/10** |

**Build & Parity Checks**:
- `./script/docs`: PASS / FAIL
- `./script/lint` (`codespell`): PASS / FAIL
- Component / MCP / Config Parity: PASS / FAIL (list any drift)

**4-Persona Cold-Read Findings**:
- **Pi/NAS Sync-Only**: ...
- **Local-First / Ollama**: ...
- **AI Power User**: ...
- **Developer / Plugin Author**: ...

**Blocking Fixes (Score 0 or Drift)**:
1. ...

**Polish Recommendations**:
1. ...
```
