# Large-Notebook Summarization Evaluation Dataset

Declarative corpus (`dataset.yaml`) for head-to-head evaluation of notebook summarization strategies (single-shot baseline vs. independent chunking vs. iterative rolling-context chunking vs. multi-layer reduction) on realistic large Supernote notebooks.

## Corpus Overview (`dataset.yaml`)

`dataset.yaml` contains **3 large notebooks (76 pages total)** targeting the main failure modes of large-notebook summarization:

1. **`Daily_2026.note` (40 pages, `custom_type: daily`)**
   - Running Q1–Q2 Bullet Journal (Jan–Apr 2026) mixing high-signal milestones (half-marathon training, home solar install, kitchen remodel, tax prep, family events) with mundane daily noise (groceries, errands).
   - **Boundary-spanning undated continuations** placed across common chunk boundaries (pages 8→9, 15→16, 24→25, 30→31) to test `carry_over_context` and date-aware splitting.
   - **Blank pages** (pages 12 and 28) to verify 1-indexed `page_refs` remain aligned to physical notebook page numbers.
   - **`incremental_updates`**: includes both a trailing 2-page append and a mid-notebook edit (page 20) to measure incremental cache hit rates and edit propagation.

2. **`Weekly_Work_Log.note` (20 pages, `custom_type: weekly`)**
   - Engineering sprint logs, architecture reviews, and incident postmortems.
   - **Dense pages (2,000+ chars)** that trigger `max_chars_per_chunk` before `max_pages_per_chunk`.
   - **Legacy undated `page_id`s** (`LEGACY_PAGE_*`) on continuation pages where neither the page header nor `page_id` carries a date, directly testing rolling carry-over context.

3. **`Project_Helios_Design.note` (16 pages, `custom_type: default`)**
   - Non-chronological technical design notebook (solar weather station BOM, firmware state machine, field tests, thermal benchmarks) with sparse dates and revised specs.

## Ground-Truth Expectations

Each notebook declares `expected_facts` tagged by `region` (`early`, `middle`, `late`, `boundary_continuation`) with:
- `expected_date`: ISO `YYYY-MM-DD` date expected in `extracted_dates` or `date_range`.
- `expected_page`: 1-indexed page number expected in `page_refs`.
- `keywords`: list of keyword groups (each group is a string or list of acceptable synonyms; all groups must match in the summary).

This enables fair head-to-head scoring across strategies on:
- Overall & per-region fact recall (specifically catching lost-in-the-middle and boundary-continuation drops)
- Date extraction & `page_refs` citation accuracy
- Duplicate/fragmented `date_range` rate
- LLM call count, token usage, and latency (initial run + incremental append/edit)
