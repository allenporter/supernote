# LLM Wiki Backfill Evaluation Suite

Repeatable multi-notebook corpus and evaluation harness for measuring LLM Wiki backfill quality against real LLMs (Gemini, OpenAI, Ollama) or an offline deterministic stub.

## Dataset (`dataset.yaml`)

`dataset.yaml` seeds an isolated ephemeral SQLite database with:

- **18 notebooks** (16 OCR'd multi-page/daily/project notes spanning 4 backfill batches of 5, plus 2 un-OCR'd scratchpads).
- **8 Schedule tasks** tied to the same projects.
- **Recurring cross-notebook themes & evolving decisions**:
  - **Aurora Home Server** (32GB non-ECC + Unraid -> 64GB ECC + TrueNAS Scale, 28W idle).
  - **Q4 Cloud Release (v0.28)** (Nov 15 -> Nov 22 deadline, 118ms hybrid search p95, `Alice` / `Al1ce` OCR alias hygiene).
  - **Kyoto Autumn Trip** (Gion Ryokan -> Higashiyama Machiya, `Maya` & `Leo`).
  - **Recurring topics**: Strength Training, Reading Notes (DDIA & Design of Everyday Things), Garden & Composting.

## Running the Eval

```bash
# Offline smoke run with deterministic fake model:
uv run --no-sync python script/eval_wiki.py --target fake:deterministic --export-dir /tmp/wiki_eval_fake

# Real Gemini run (requires GEMINI_API_KEY or SUPERNOTE_GEMINI_API_KEY):
uv run --no-sync python script/eval_wiki.py \
  --target gemini:gemini-2.5-flash \
  --export-dir /tmp/wiki_eval_gemini

# Real OpenAI or local Ollama run:
uv run --no-sync python script/eval_wiki.py \
  --target openai:gpt-4o-mini \
  --export-dir /tmp/wiki_eval_openai
```

When `--export-dir` is provided, the runner writes:
- `<export-dir>/vault/**/*.md` — Obsidian-compatible Markdown files for every compiled wiki page.
- `<export-dir>/report.md` — Human-readable quality summary (non-source page ratio, `index` presence, wikilink density, open lint counts, concept & evolved-fact recall).
- `<export-dir>/report.json` — Machine-readable metrics and batch traces for before/after comparisons.
