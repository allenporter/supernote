# OCR Evaluation Suite

Provider-agnostic benchmark suite for comparing page OCR backends (`apple`, `gemini`, `openai`/Ollama/llama.cpp/vLLM, `fake`, and Supernote on-device RTR) across Bullet Journal Rapid Logging notebooks and real-world `.note` fixtures.

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
- **`device-rtr`** ([`results/device_rtr.json`](results/device_rtr.json)): Scores the pre-computed `RECOGNTEXT` layer embedded inside Supernote Real-Time Recognition `.note` files (`8` pages in `dataset.yaml`). Notably, `french_phrases.note` and `spanish_lessons.note` were recorded on-device while the notebook language was left at `en_US`, yielding `15.0%` multilingual CER (`82.1%` Word Recall) on embedded RTR.
- **`supernote-on-device`** ([`results/supernote_on_device.json`](results/supernote_on_device.json)): Supernote Chauvet `3.30.45` on-device handwriting recognition (`MyScript iink 4.1.0`) across all `25` vector-stroke `.note` pages in `dataset.yaml` (the `5` synthetic Bullet Journal fixtures are raster-only bitmaps without a vector stroke layer). When run with the matching `fr_FR`, `es_ES`, and `tr_TR` dictionaries, multilingual CER drops from `15.0%` (`device-rtr`) to `4.4%` (`94.9%` Word Recall). On real handwritten Bullet Journal pages, word recall remains solid (`95.0%` daily, `79.6%` monthly), but Rapid Logging signifiers (`X`, `>`, `<`, `o`) and horizontal strikethroughs (`0.0%` recall) are not preserved semantically. Supernote's recognizer also intentionally excludes Marker/Highlighter strokes (`1to10.note` giant digits and `inverted_banner_scribble_overlap` overlays).
- **`gemini:gemini-3.5-flash-lite` / `gemini:gemini-3.6-flash` / `gemini:gemini-3.8-flash`** ([`results/gemini.json`](results/gemini.json)): Evaluated across all `30` pages. `gemini-3.5-flash-lite` achieves the lowest overall Mean CER (`2.3%`, `0.0%` Median CER, `1.7%` Content CER, `99.2%` Word Recall, `97.1%` BuJo Symbol Recall, `0` errors) at `1.18 s` median / `1.42 s` P95 latency. `gemini-3.6-flash` posts the highest overall Word Recall (`99.9%`) and BuJo Symbol Recall (`98.1%`) plus `2.3%` multilingual CER, while rendering ASCII pipe (`|`) columns on 2D guitar fretboard diagrams (`4.2%` overall Mean CER, `6.63 s` median latency). `gemini-3.8-flash` achieves the lowest multilingual CER (`2.1%`) across French, Spanish, and Turkish, but spends >90 s of reasoning tokens aligning the 12-fret `guitar_tuning_grid` tablature (`1` timeout error under the default `90 s` `--page-timeout`).

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

## Notebooks in `notebooks/`

Real handwritten Supernote `.note` fixtures (`TOTALPATH` vector strokes + `MAINLAYER` bitmaps):

| Notebook | Pages Evaluated | Category | Notes |
| :--- | ---: | :--- | :--- |
| [bujo_daily_weekend.note](notebooks/bujo_daily_weekend.note) | `1` (`p0`) | `bujo_daily` | Handwritten weekend Rapid Logging (`X`, `>`, `o`, `•`) on Nomad dot-grid. |
| [bujo_monthly_november.note](notebooks/bujo_monthly_november.note) | `2` (`p0–p1`) | `bujo_monthly` | Handwritten November backlog (`-`, `X`, `<`, `•`, strikethrough) + `1–30` calendar timeline. |
| [guitar_theory.note](notebooks/guitar_theory.note) | `2` (`p0–p1`) | `diagram_and_layout` | Two-column CAGED fretboard diagrams + 12-fret C tuning & song tab grid. |
| [french_phrases.note](notebooks/french_phrases.note) | `3` (`p0–p2`) | `multilingual` (`fr_FR`) | Bilingual French/English café, travel, and verb notes (includes embedded RTR). |
| [spanish_lessons.note](notebooks/spanish_lessons.note) | `2` (`p0, p6`) | `multilingual` (`es_ES`) | Bilingual Spanish/English cognate & sentence drills (includes embedded RTR). |

Synthetic Bullet Journal fixtures (`notebooks/{daily,weekly,monthly}.note`) and their rendered `.png` previews are generated deterministically with [generate_bujo_eval_notes.py](../../script/generate_bujo_eval_notes.py):

| Case ID | Notebook | Page | Rendered Preview |
| :--- | :--- | ---: | :--- |
| `bujo_daily_friday` | [daily.note](notebooks/daily.note) | `0` | [daily_page_0.png](notebooks/daily_page_0.png) |
| `bujo_daily_saturday` | [daily.note](notebooks/daily.note) | `1` | [daily_page_1.png](notebooks/daily_page_1.png) |
| `bujo_weekly_w45` | [weekly.note](notebooks/weekly.note) | `0` | [weekly_page_0.png](notebooks/weekly_page_0.png) |
| `bujo_monthly_calendar` | [monthly.note](notebooks/monthly.note) | `0` | [monthly_page_0.png](notebooks/monthly_page_0.png) |
| `bujo_monthly_goals` | [monthly.note](notebooks/monthly.note) | `1` | [monthly_page_1.png](notebooks/monthly_page_1.png) |
