# OCR Evaluation Suite

Provider-agnostic benchmark suite for comparing page OCR backends (`apple`, `gemini`, `openai`/Ollama/llama.cpp/vLLM, `fake`, and embedded Supernote on-device RTR) across Bullet Journal Rapid Logging notebooks and real-world `.note` fixtures.

See [**RESULTS.md**](RESULTS.md) for the current checked-in provider comparison table (and [`results/`](results/) for per-provider JSON transcripts and metrics).

## Quick Start

```bash
# Run on macOS with local Apple Vision (`vision-accurate` vs `vision-fast`) + embedded device RTR
./script/eval_ocr.py \
  --target apple:vision-accurate \
  --target apple:vision-fast \
  --include-device-rtr

# Compare Apple Vision against a local Ollama vision model and Gemini
./script/eval_ocr.py \
  --target apple:vision-accurate \
  --target openai:gemma3:27b \
  --openai-base-url http://localhost:11434/v1 \
  --target gemini:gemini-3.6-flash \
  --markdown-out storage/eval_ocr_report.md \
  --json-out storage/eval_ocr_results.json

# Run only Bullet Journal Rapid Logging categories
./script/eval_ocr.py \
  --category bujo_daily \
  --category bujo_weekly \
  --category bujo_monthly
```

You can also pass `--config config/config.yaml` to reference named provider entries from `ai.providers` (e.g. `--target ollama:gemma3:27b --target llamacpp:qwen2.5-vl`).

## Recording & Merging Provider Results

Checked-in benchmark runs are stored as standalone JSON files in [`results/`](results/) so new providers can be evaluated incrementally on different machines (macOS Apple Silicon, Linux GPU, cloud APIs) without re-running existing providers:

```bash
# 1. Run a new provider and save its standalone per-page JSON results
./script/eval_ocr.py \
  --target openai:gemma3:27b \
  --openai-base-url http://localhost:11434/v1 \
  --json-out evals/ocr/results/ollama_gemma3_27b.json

# 2. Merge all saved JSON runs into RESULTS.md (no live inference required)
./script/eval_ocr.py \
  --from-json evals/ocr/results/*.json \
  --markdown-out evals/ocr/RESULTS.md
```

### Provider Notes

- **`apple:vision-accurate` vs `apple:vision-fast`** ([`results/apple.json`](results/apple.json)): `vision-accurate` uses Apple's neural recognizer (strong handwriting recall on prose and Bullet Journal pages), whereas `vision-fast` uses Vision's legacy contour detector intended for machine-printed text. On Rapid Logging pages, `vision-accurate` currently transcribes hand-drawn `X` crosses as `×` (`\u00d7`), flattens leading indentation (`boundingBox.origin.x` is not yet mapped to indent spaces), and reads words underneath strikethrough strokes without wrapping them in `~~...~~`.
- **`device-rtr`** ([`results/device_rtr.json`](results/device_rtr.json)): Scores the pre-computed `RECOGNTEXT` layer embedded inside Supernote Real-Time Recognition `.note` files (`3` pages in `dataset.yaml`).

## Metrics Reported

- **Mean / Median CER**: Normalized Character Error Rate (`Levenshtein(ref, hyp) / len(ref)`), including Rapid Logging symbols and formatting.
- **Content CER**: Character Error Rate after stripping leading Rapid Logging signifiers (`*`, `•`, `X`, `>`, `<`, `o`, `-`) and `~~strikethrough~~` markers—isolating raw handwriting word accuracy from prompt-driven symbol formatting.
- **Word Recall**: Case-insensitive alphanumeric word recall (`0%–100%`).
- **BuJo Symbol Recall**: Fraction of Rapid Logging items in `ground_truth` whose matching transcribed line preserves the canonical bullet (`•`, `X`, `>`, `<`, `o`, `-`) and critical star (`* `) defined in [legend.md](../../supernote/server/resources/prompts/ocr/common/legend.md).
- **BuJo Indent / BuJo Strike**: Preservation of 2-space nested hierarchy and `~~crossed out~~` strikethrough spans on Bullet Journal pages.
- **Median / P95 Latency**: Per-page inference wall-clock time (after a single unmeasured warmup call).

## Adding Real `.note` or `.png` Pages

Drop a `.note` notebook or `.png` page into `evals/ocr/notebooks/` (or anywhere relative to [dataset.yaml](dataset.yaml)) and add an entry to [dataset.yaml](dataset.yaml):

```yaml
  - id: my_daily_log_p0
    path: notebooks/my_daily.note
    page_index: 0
    category: bujo_daily
    prompt_type: daily
    description: Real handwritten daily log page.
    ground_truth: |-
      2026-11-09 Sunday
      * • Buy groceries for week
      X Morning run 5km
```

## Bullet Journal Fixtures

Synthetic Bullet Journal fixtures (`notebooks/{daily,weekly,monthly}.note`) and their rendered `.png` previews are generated deterministically with [generate_bujo_eval_notes.py](../../script/generate_bujo_eval_notes.py):

| Case ID | Notebook | Page | Rendered Preview |
| :--- | :--- | ---: | :--- |
| `bujo_daily_friday` | [daily.note](notebooks/daily.note) | `0` | [daily_page_0.png](notebooks/daily_page_0.png) |
| `bujo_daily_saturday` | [daily.note](notebooks/daily.note) | `1` | [daily_page_1.png](notebooks/daily_page_1.png) |
| `bujo_weekly_w45` | [weekly.note](notebooks/weekly.note) | `0` | [weekly_page_0.png](notebooks/weekly_page_0.png) |
| `bujo_monthly_nov_calendar` | [monthly.note](notebooks/monthly.note) | `0` | [monthly_page_0.png](notebooks/monthly_page_0.png) |
| `bujo_monthly_nov_tasks` | [monthly.note](notebooks/monthly.note) | `1` | [monthly_page_1.png](notebooks/monthly_page_1.png) |
