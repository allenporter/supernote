# LLM Wiki Backfill Evaluation Suite

Repeatable multi-notebook corpus and evaluation harness for measuring LLM Wiki backfill quality against real LLMs (Gemini, OpenAI, Ollama) or an offline deterministic stub.

## Dataset (`dataset.yaml`)

`dataset.yaml` seeds an isolated ephemeral SQLite database with:

- **19 notebooks** (17 OCR'd notebooks totaling **56 transcribed pages**—including a 24-page daily bullet journal and 3–4 page project/reading notebooks spanning 4 backfill batches of 5—plus 2 un-OCR'd scratchpads).
- **8 Schedule tasks** tied to the same projects.
- **Recurring cross-notebook themes & evolving decisions**:
  - **Aurora Home Server** (32GB non-ECC + Unraid -> 64GB ECC + TrueNAS Scale, 28W idle).
  - **Q4 Cloud Release (v0.28)** (Nov 15 -> Nov 22 deadline, 118ms hybrid search p95, `Alice` / `Al1ce` OCR alias hygiene).
  - **Kyoto Autumn Trip** (Gion Ryokan -> Higashiyama Machiya, `Maya` & `Leo`).
  - **Recurring topics**: Strength Training, Reading Notes (DDIA & Design of Everyday Things), Garden & Composting.

## Daily / Monthly / Quarterly Planner Dataset (`daily_log_dataset.yaml`)

`daily_log_dataset.yaml` is a standalone chronological planner corpus with **no dedicated topic notebooks**:

- **`Daily.note`** (30 days of running bullet-journal logs, Oct 25 – Nov 23, packed across 11 pages with 1 to 4 days per page) mixing fleeting errands with recurring project updates.
- **`Monthly_Log_2026.note`** (October & November monthly calendar highlights, migrated tasks, and habit trackers).
- **`Monthly_Reflections_2026.note`** (September & October monthly reflections covering wins, energy drains, and adjustments).
- **`Q3_2026_Quarterly_Reflection.note`** (Q3 quarterly review and Q4 goals/themes).

Use it to evaluate whether the wiki compiler extracts durable projects, people, habits, reflection themes, and evolved decisions from chronological daily/monthly/quarterly logs alone:

```bash
uv run --no-sync python script/eval_wiki.py \
  --dataset evals/wiki/daily_log_dataset.yaml \
  --target gemini:gemini-3.5-flash-lite \
  --max-files-per-batch 1 \
  --export-dir /tmp/wiki_eval_daily_log
```

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
