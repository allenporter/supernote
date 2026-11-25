# Search & Embedding Evaluation Suite

Benchmark suite for evaluating Supernote page search retrieval across native `#keyword` metadata tags (`NotePageMetadataDO`), OCR transcripts (`NotePageContentDO`), and dense vector embeddings (`GeminiEmbeddingModel`, `OpenAIEmbeddingModel` / Ollama).

See [**RESULTS.md**](RESULTS.md) for the checked-in comparison table across cloud and local embedding models (and [`results/`](results/) for per-model JSON traces).

## Recommended Embedding Models

When paired with Supernote's hybrid search (`SearchService`, combining `EmbeddingChunkSearcher` and `KeywordChunkSearcher`):

- **Recommended Cloud Model — `gemini:gemini-embedding-2`**: Achieves **`97.1%` nDCG@5 / `97.6%` nDCG@10** and **`100.0%` MRR@5** (`50/50` rank-1 hits across all answerable queries, `99.5%` nDCG@5 on zero-keyword-overlap `semantic_paraphrase`), ahead of `gemini-embedding-001` (`95.5%` nDCG@5, `98.0%` MRR@5) and `openai:text-embedding-3-small` (`94.0%` nDCG@5, `98.0%` MRR@5).
- **Recommended Local / Self-Hosted Model — `embeddinggemma`** (via Ollama / llama.cpp): Achieves **`93.7%` nDCG@5 / `94.3%` nDCG@10** and **`97.0%` MRR@5** in **`23.5 ms`** median query latency (`308M` parameters, `593 MB` model size, `768`-dim vectors), outperforming both `qwen3-embedding:0.6b` (`91.3%`) and `qwen3-embedding:4b` (`92.2%`) while matching cloud `text-embedding-3-small` (`94.2%` nDCG@10) completely offline.

## Retrieval Modes Evaluated

All five modes run against the exact same indexed SQLite corpus at `top_n=5` (MCP `search_notes` default) and `top_n=10` (Web UI modal):

- **`random`**: Deterministic uniform random baseline over active `.note` pages matching scope filters (`name_filter`, `date_after`, `date_before`).
- **`keyword_only`**: `SearchService` with `embedding_model=None` (`KeywordChunkSearcher` over native page keywords and SQL-prefiltered OCR transcripts).
- **`embedding_unfloored`**: Pure cosine similarity ranking without a minimum similarity floor.
- **`embedding_floored`**: Pure `EmbeddingChunkSearcher` cosine similarity ranking with the `0.25` minimum similarity floor.
- **`hybrid`**: Full `SearchService` (`EmbeddingChunkSearcher` + `KeywordChunkSearcher` + `0.25` vector floor + monotonic score fusion).

## Quick Start

```bash
# Run against Gemini embeddings (caches vectors locally in storage/eval_search_cache/)
SUPERNOTE_GEMINI_API_KEY=... ./script/eval_search.py \
  --target gemini:gemini-embedding-2 \
  --json-out evals/search/results/gemini_embedding_2.json

# Run against OpenAI embeddings
SUPERNOTE_OPENAI_API_KEY=... ./script/eval_search.py \
  --target openai:text-embedding-3-small \
  --json-out evals/search/results/openai_text_embedding_3_small.json

# Run against a local Ollama server
./script/eval_search.py \
  --target ollama:embeddinggemma \
  --ollama-base-url http://localhost:11434/v1 \
  --json-out evals/search/results/ollama_embeddinggemma.json

# Merge all saved JSON runs into RESULTS.md (zero live API calls)
./script/eval_search.py \
  --from-json \
    evals/search/results/gemini_embedding_001.json \
    evals/search/results/gemini_embedding_2.json \
    evals/search/results/openai_text_embedding_3_small.json \
    evals/search/results/ollama_embeddinggemma.json \
    evals/search/results/ollama_qwen3_embedding_0_6b.json \
    evals/search/results/ollama_qwen3_embedding_4b.json \
  --rescore \
  --markdown-out evals/search/RESULTS.md

# Offline smoke run using deterministic FakeEmbeddingModel(blended=True)
./script/eval_search.py --target fake:blended --no-cache
```

## Dataset & Anti-Bias Ground-Truth Construction

[`dataset.yaml`](dataset.yaml) (`supernote-search-suite-v1`) contains `100` pages across `26` notebooks and `60` ground-truth queries, combining `25` real Gemini OCR transcripts from [`evals/ocr/`](../ocr/) with `75` realistic multi-page personal and engineering pages (Bullet Journal Rapid Logging, meeting notes, reading notes, bilingual Japanese/French/Spanish/Turkish pages, native Supernote page keywords, legacy undated pages, and realistic OCR typos).

To prevent algorithm leakage into the ground truth, the synthetic corpus, queries, and graded relevance labels (`2` = primary target page, `1` = secondary/partial match) were constructed via a three-stage blind pipeline without access to `supernote/server/components/search/`:

1. **Corpus Authors**: Authored multi-notebook pages and native Supernote keywords without knowledge of downstream search queries.
2. **Query Author**: Authored queries across six user-intent categories (`tag_lookup`, `exact_lexical`, `semantic_paraphrase`, `hybrid_intent`, `scoped_filters`, `unanswerable_negative`) from the corpus alone.
3. **Relevance Judge**: Independently audited every query against all `100` pages to surface missed relevant pages and verify zero-relevance negative queries before running any retrieval mode.

## Metrics Reported

Evaluated at both `top_n=5` and `top_n=10`:

- **`nDCG@k`** *(answerable queries)*: Normalized Discounted Cumulative Gain with exponential graded gain `(2**grade - 1) / log2(rank + 1)`.
- **`MRR@k`** *(answerable queries)*: Mean Reciprocal Rank (`1 / rank`) of the highest-ranked relevant page (`grade >= 1`).
- **`Recall@k`** *(answerable queries)*: Fraction of all ground-truth relevant pages (`grade >= 1`) retrieved within `top_n=k`.
- **`Precision@k`** *(answerable queries)*: Fraction of returned result cards (`hits[:k]`) that are relevant (`0%` if empty), directly measuring low-relevance result padding when fewer than `k` pages in the vault match.
- **`Abstention Rate`** *(`unanswerable_negative` queries)*: Percentage of unanswerable queries where search returns an empty result list (`[]`) instead of unrelated false positives.
