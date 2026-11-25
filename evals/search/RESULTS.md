# Search Retrieval Evaluation Report: `supernote-search-suite-v1`

- **Corpus**: `100` pages across `26` notebooks
- **Queries**: `60` ground-truth queries
- **Embedding Model**: `gemini:gemini-embedding-001, gemini:gemini-embedding-2, openai:text-embedding-3-small, ollama:embeddinggemma, ollama:qwen3-embedding:0.6b, ollama:qwen3-embedding:4b`

## Overall Summary (`top_n=5`)

| Mode | Embedding | Answerable | Unanswerable | nDCG@5 | MRR@5 | Recall@5 | Precision@5 | Abstention Rate | Median Latency |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `random` | `none` | 50 | 10 | 16.0% | 16.1% | 20.9% | 10.8% | 0.0% | 1.7 ms |
| `keyword_only` | `none` | 50 | 10 | 54.8% | 59.0% | 49.3% | 54.3% | 90.0% | 4.0 ms |
| `embedding_unfloored` | `gemini:gemini-embedding-001` | 50 | 10 | 87.9% | 90.8% | 88.4% | 31.2% | 0.0% | 173.7 ms |
| `embedding_floored` | `gemini:gemini-embedding-001` | 50 | 10 | 87.9% | 90.8% | 88.4% | 31.2% | 0.0% | 64.1 ms |
| `hybrid` | `gemini:gemini-embedding-001` | 50 | 10 | 95.5% | 98.0% | 93.2% | 34.8% | 0.0% | 69.4 ms |
| `embedding_unfloored` | `gemini:gemini-embedding-2` | 50 | 10 | 86.4% | 89.7% | 85.3% | 30.4% | 0.0% | 184.4 ms |
| `embedding_floored` | `gemini:gemini-embedding-2` | 50 | 10 | 86.4% | 89.7% | 85.3% | 30.4% | 0.0% | 64.1 ms |
| `hybrid` | `gemini:gemini-embedding-2` | 50 | 10 | 97.1% | 100.0% | 93.7% | 34.8% | 0.0% | 68.8 ms |
| `embedding_unfloored` | `openai:text-embedding-3-small` | 50 | 10 | 82.7% | 87.4% | 82.7% | 28.4% | 0.0% | 148.3 ms |
| `embedding_floored` | `openai:text-embedding-3-small` | 50 | 10 | 77.6% | 85.0% | 73.7% | 43.0% | 0.0% | 46.2 ms |
| `hybrid` | `openai:text-embedding-3-small` | 50 | 10 | 94.0% | 98.0% | 89.5% | 52.5% | 0.0% | 50.9 ms |
| `embedding_unfloored` | `ollama:embeddinggemma` | 50 | 10 | 77.4% | 80.7% | 77.5% | 26.8% | 0.0% | 38.9 ms |
| `embedding_floored` | `ollama:embeddinggemma` | 50 | 10 | 76.6% | 80.7% | 76.5% | 30.7% | 0.0% | 19.1 ms |
| `hybrid` | `ollama:embeddinggemma` | 50 | 10 | 93.7% | 97.0% | 90.2% | 37.1% | 0.0% | 23.5 ms |
| `embedding_unfloored` | `ollama:qwen3-embedding:0.6b` | 50 | 10 | 72.9% | 75.7% | 76.0% | 26.8% | 0.0% | 42.9 ms |
| `embedding_floored` | `ollama:qwen3-embedding:0.6b` | 50 | 10 | 72.9% | 75.7% | 76.0% | 26.8% | 0.0% | 24.4 ms |
| `hybrid` | `ollama:qwen3-embedding:0.6b` | 50 | 10 | 91.3% | 95.7% | 89.8% | 34.0% | 0.0% | 28.9 ms |
| `embedding_unfloored` | `ollama:qwen3-embedding:4b` | 50 | 10 | 72.5% | 74.0% | 74.8% | 26.0% | 0.0% | 83.9 ms |
| `embedding_floored` | `ollama:qwen3-embedding:4b` | 50 | 10 | 72.5% | 74.0% | 74.8% | 26.1% | 0.0% | 53.9 ms |
| `hybrid` | `ollama:qwen3-embedding:4b` | 50 | 10 | 92.2% | 95.7% | 89.7% | 33.3% | 0.0% | 58.9 ms |

## Overall Summary (`top_n=10`)

| Mode | Embedding | Answerable | Unanswerable | nDCG@10 | MRR@10 | Recall@10 | Precision@10 | Abstention Rate | Median Latency |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `random` | `none` | 50 | 10 | 15.0% | 14.4% | 20.3% | 9.5% | 0.0% | 1.7 ms |
| `keyword_only` | `none` | 50 | 10 | 54.8% | 59.0% | 49.3% | 53.8% | 90.0% | 4.0 ms |
| `embedding_unfloored` | `gemini:gemini-embedding-001` | 50 | 10 | 88.9% | 90.8% | 91.5% | 20.5% | 0.0% | 173.7 ms |
| `embedding_floored` | `gemini:gemini-embedding-001` | 50 | 10 | 88.9% | 90.8% | 91.5% | 20.5% | 0.0% | 64.1 ms |
| `hybrid` | `gemini:gemini-embedding-001` | 50 | 10 | 96.0% | 98.0% | 95.5% | 21.7% | 0.0% | 69.4 ms |
| `embedding_unfloored` | `gemini:gemini-embedding-2` | 50 | 10 | 87.9% | 90.2% | 89.2% | 20.1% | 0.0% | 184.4 ms |
| `embedding_floored` | `gemini:gemini-embedding-2` | 50 | 10 | 87.9% | 90.2% | 89.2% | 20.1% | 0.0% | 64.1 ms |
| `hybrid` | `gemini:gemini-embedding-2` | 50 | 10 | 97.6% | 100.0% | 95.5% | 21.7% | 0.0% | 68.8 ms |
| `embedding_unfloored` | `openai:text-embedding-3-small` | 50 | 10 | 84.0% | 87.7% | 85.5% | 19.1% | 0.0% | 148.3 ms |
| `embedding_floored` | `openai:text-embedding-3-small` | 50 | 10 | 78.9% | 85.3% | 76.5% | 39.5% | 0.0% | 46.2 ms |
| `hybrid` | `openai:text-embedding-3-small` | 50 | 10 | 94.2% | 98.0% | 90.5% | 45.6% | 0.0% | 50.9 ms |
| `embedding_unfloored` | `ollama:embeddinggemma` | 50 | 10 | 79.8% | 81.6% | 84.8% | 18.9% | 0.0% | 38.9 ms |
| `embedding_floored` | `ollama:embeddinggemma` | 50 | 10 | 77.9% | 81.0% | 81.3% | 25.0% | 0.0% | 19.1 ms |
| `hybrid` | `ollama:embeddinggemma` | 50 | 10 | 94.3% | 97.0% | 93.3% | 27.9% | 0.0% | 23.5 ms |
| `embedding_unfloored` | `ollama:qwen3-embedding:0.6b` | 50 | 10 | 74.4% | 76.3% | 81.4% | 18.3% | 0.0% | 42.9 ms |
| `embedding_floored` | `ollama:qwen3-embedding:0.6b` | 50 | 10 | 74.4% | 76.3% | 81.4% | 18.3% | 0.0% | 24.4 ms |
| `hybrid` | `ollama:qwen3-embedding:0.6b` | 50 | 10 | 92.5% | 96.0% | 94.3% | 21.5% | 0.0% | 28.9 ms |
| `embedding_unfloored` | `ollama:qwen3-embedding:4b` | 50 | 10 | 75.0% | 74.7% | 82.7% | 18.5% | 0.0% | 83.9 ms |
| `embedding_floored` | `ollama:qwen3-embedding:4b` | 50 | 10 | 75.0% | 74.7% | 82.7% | 18.8% | 0.0% | 53.9 ms |
| `hybrid` | `ollama:qwen3-embedding:4b` | 50 | 10 | 93.0% | 95.7% | 93.7% | 21.6% | 0.0% | 58.9 ms |

## Breakdown by Query Category (`top_n=5`)

| Mode | Embedding | Category | Queries | nDCG@5 | MRR@5 | Recall@5 | Precision@5 | Abstention Rate |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `random` | `none` | `tag_lookup` | 10 | 2.7% | 5.3% | 7.0% | 4.0% | — |
| `random` | `none` | `exact_lexical` | 10 | 6.3% | 5.0% | 10.0% | 2.0% | — |
| `random` | `none` | `semantic_paraphrase` | 12 | 3.6% | 2.1% | 8.3% | 1.7% | — |
| `random` | `none` | `hybrid_intent` | 10 | 16.6% | 20.0% | 12.5% | 4.0% | — |
| `random` | `none` | `scoped_filters` | 8 | 62.5% | 59.4% | 81.2% | 52.3% | — |
| `random` | `none` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `keyword_only` | `none` | `tag_lookup` | 10 | 89.0% | 100.0% | 71.7% | 90.0% | — |
| `keyword_only` | `none` | `exact_lexical` | 10 | 88.3% | 90.0% | 85.0% | 90.0% | — |
| `keyword_only` | `none` | `semantic_paraphrase` | 12 | 0.0% | 0.0% | 0.0% | 0.0% | — |
| `keyword_only` | `none` | `hybrid_intent` | 10 | 32.5% | 35.0% | 30.0% | 21.7% | — |
| `keyword_only` | `none` | `scoped_filters` | 8 | 80.5% | 87.5% | 75.0% | 87.5% | — |
| `keyword_only` | `none` | `unanswerable_negative` | 10 | — | — | — | — | 90.0% |
| `embedding_unfloored` | `gemini:gemini-embedding-001` | `tag_lookup` | 10 | 66.7% | 73.3% | 68.7% | 30.0% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-001` | `exact_lexical` | 10 | 85.9% | 85.8% | 92.5% | 22.0% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-001` | `semantic_paraphrase` | 12 | 96.5% | 95.8% | 100.0% | 21.7% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-001` | `hybrid_intent` | 10 | 91.4% | 100.0% | 80.8% | 28.0% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-001` | `scoped_filters` | 8 | 99.4% | 100.0% | 100.0% | 62.3% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-001` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_floored` | `gemini:gemini-embedding-001` | `tag_lookup` | 10 | 66.7% | 73.3% | 68.7% | 30.0% | — |
| `embedding_floored` | `gemini:gemini-embedding-001` | `exact_lexical` | 10 | 85.9% | 85.8% | 92.5% | 22.0% | — |
| `embedding_floored` | `gemini:gemini-embedding-001` | `semantic_paraphrase` | 12 | 96.5% | 95.8% | 100.0% | 21.7% | — |
| `embedding_floored` | `gemini:gemini-embedding-001` | `hybrid_intent` | 10 | 91.4% | 100.0% | 80.8% | 28.0% | — |
| `embedding_floored` | `gemini:gemini-embedding-001` | `scoped_filters` | 8 | 99.4% | 100.0% | 100.0% | 62.3% | — |
| `embedding_floored` | `gemini:gemini-embedding-001` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `hybrid` | `gemini:gemini-embedding-001` | `tag_lookup` | 10 | 95.6% | 100.0% | 90.0% | 44.0% | — |
| `hybrid` | `gemini:gemini-embedding-001` | `exact_lexical` | 10 | 100.0% | 100.0% | 100.0% | 28.0% | — |
| `hybrid` | `gemini:gemini-embedding-001` | `semantic_paraphrase` | 12 | 96.5% | 95.8% | 100.0% | 21.7% | — |
| `hybrid` | `gemini:gemini-embedding-001` | `hybrid_intent` | 10 | 86.8% | 95.0% | 75.8% | 26.0% | — |
| `hybrid` | `gemini:gemini-embedding-001` | `scoped_filters` | 8 | 99.4% | 100.0% | 100.0% | 62.3% | — |
| `hybrid` | `gemini:gemini-embedding-001` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_unfloored` | `gemini:gemini-embedding-2` | `tag_lookup` | 10 | 63.3% | 73.3% | 62.3% | 28.0% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-2` | `exact_lexical` | 10 | 75.9% | 75.0% | 80.0% | 18.0% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-2` | `semantic_paraphrase` | 12 | 99.5% | 100.0% | 100.0% | 21.7% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-2` | `hybrid_intent` | 10 | 93.2% | 100.0% | 84.2% | 30.0% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-2` | `scoped_filters` | 8 | 100.0% | 100.0% | 100.0% | 62.3% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-2` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_floored` | `gemini:gemini-embedding-2` | `tag_lookup` | 10 | 63.3% | 73.3% | 62.3% | 28.0% | — |
| `embedding_floored` | `gemini:gemini-embedding-2` | `exact_lexical` | 10 | 75.9% | 75.0% | 80.0% | 18.0% | — |
| `embedding_floored` | `gemini:gemini-embedding-2` | `semantic_paraphrase` | 12 | 99.5% | 100.0% | 100.0% | 21.7% | — |
| `embedding_floored` | `gemini:gemini-embedding-2` | `hybrid_intent` | 10 | 93.2% | 100.0% | 84.2% | 30.0% | — |
| `embedding_floored` | `gemini:gemini-embedding-2` | `scoped_filters` | 8 | 100.0% | 100.0% | 100.0% | 62.3% | — |
| `embedding_floored` | `gemini:gemini-embedding-2` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `hybrid` | `gemini:gemini-embedding-2` | `tag_lookup` | 10 | 94.2% | 100.0% | 86.7% | 42.0% | — |
| `hybrid` | `gemini:gemini-embedding-2` | `exact_lexical` | 10 | 99.6% | 100.0% | 100.0% | 28.0% | — |
| `hybrid` | `gemini:gemini-embedding-2` | `semantic_paraphrase` | 12 | 99.5% | 100.0% | 100.0% | 21.7% | — |
| `hybrid` | `gemini:gemini-embedding-2` | `hybrid_intent` | 10 | 92.3% | 100.0% | 81.7% | 28.0% | — |
| `hybrid` | `gemini:gemini-embedding-2` | `scoped_filters` | 8 | 100.0% | 100.0% | 100.0% | 62.3% | — |
| `hybrid` | `gemini:gemini-embedding-2` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_unfloored` | `openai:text-embedding-3-small` | `tag_lookup` | 10 | 51.8% | 60.0% | 52.5% | 20.0% | — |
| `embedding_unfloored` | `openai:text-embedding-3-small` | `exact_lexical` | 10 | 75.7% | 82.0% | 82.5% | 20.0% | — |
| `embedding_unfloored` | `openai:text-embedding-3-small` | `semantic_paraphrase` | 12 | 96.9% | 95.8% | 100.0% | 21.7% | — |
| `embedding_unfloored` | `openai:text-embedding-3-small` | `hybrid_intent` | 10 | 90.4% | 100.0% | 78.3% | 26.0% | — |
| `embedding_unfloored` | `openai:text-embedding-3-small` | `scoped_filters` | 8 | 99.0% | 100.0% | 100.0% | 62.3% | — |
| `embedding_unfloored` | `openai:text-embedding-3-small` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_floored` | `openai:text-embedding-3-small` | `tag_lookup` | 10 | 50.4% | 60.0% | 47.5% | 34.0% | — |
| `embedding_floored` | `openai:text-embedding-3-small` | `exact_lexical` | 10 | 70.5% | 80.0% | 67.5% | 33.0% | — |
| `embedding_floored` | `openai:text-embedding-3-small` | `semantic_paraphrase` | 12 | 96.9% | 95.8% | 100.0% | 46.4% | — |
| `embedding_floored` | `openai:text-embedding-3-small` | `hybrid_intent` | 10 | 90.4% | 100.0% | 78.3% | 26.5% | — |
| `embedding_floored` | `openai:text-embedding-3-small` | `scoped_filters` | 8 | 75.4% | 87.5% | 68.8% | 82.5% | — |
| `embedding_floored` | `openai:text-embedding-3-small` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `hybrid` | `openai:text-embedding-3-small` | `tag_lookup` | 10 | 92.4% | 100.0% | 81.7% | 60.0% | — |
| `hybrid` | `openai:text-embedding-3-small` | `exact_lexical` | 10 | 96.6% | 100.0% | 95.0% | 44.3% | — |
| `hybrid` | `openai:text-embedding-3-small` | `semantic_paraphrase` | 12 | 96.9% | 95.8% | 100.0% | 46.4% | — |
| `hybrid` | `openai:text-embedding-3-small` | `hybrid_intent` | 10 | 86.8% | 95.0% | 75.8% | 26.5% | — |
| `hybrid` | `openai:text-embedding-3-small` | `scoped_filters` | 8 | 97.6% | 100.0% | 93.8% | 95.0% | — |
| `hybrid` | `openai:text-embedding-3-small` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_unfloored` | `ollama:embeddinggemma` | `tag_lookup` | 10 | 47.8% | 53.3% | 58.3% | 22.0% | — |
| `embedding_unfloored` | `ollama:embeddinggemma` | `exact_lexical` | 10 | 54.6% | 55.0% | 55.0% | 12.0% | — |
| `embedding_unfloored` | `ollama:embeddinggemma` | `semantic_paraphrase` | 12 | 96.4% | 95.8% | 100.0% | 21.7% | — |
| `embedding_unfloored` | `ollama:embeddinggemma` | `hybrid_intent` | 10 | 89.7% | 100.0% | 74.2% | 24.0% | — |
| `embedding_unfloored` | `ollama:embeddinggemma` | `scoped_filters` | 8 | 99.0% | 100.0% | 100.0% | 62.3% | — |
| `embedding_unfloored` | `ollama:embeddinggemma` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_floored` | `ollama:embeddinggemma` | `tag_lookup` | 10 | 47.8% | 53.3% | 58.3% | 22.0% | — |
| `embedding_floored` | `ollama:embeddinggemma` | `exact_lexical` | 10 | 54.6% | 55.0% | 55.0% | 12.5% | — |
| `embedding_floored` | `ollama:embeddinggemma` | `semantic_paraphrase` | 12 | 96.4% | 95.8% | 100.0% | 23.6% | — |
| `embedding_floored` | `ollama:embeddinggemma` | `hybrid_intent` | 10 | 89.7% | 100.0% | 74.2% | 24.0% | — |
| `embedding_floored` | `ollama:embeddinggemma` | `scoped_filters` | 8 | 94.2% | 100.0% | 93.8% | 83.1% | — |
| `embedding_floored` | `ollama:embeddinggemma` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `hybrid` | `ollama:embeddinggemma` | `tag_lookup` | 10 | 91.5% | 100.0% | 79.2% | 38.0% | — |
| `hybrid` | `ollama:embeddinggemma` | `exact_lexical` | 10 | 94.6% | 95.0% | 95.0% | 26.5% | — |
| `hybrid` | `ollama:embeddinggemma` | `semantic_paraphrase` | 12 | 96.4% | 95.8% | 100.0% | 23.6% | — |
| `hybrid` | `ollama:embeddinggemma` | `hybrid_intent` | 10 | 87.4% | 95.0% | 76.7% | 26.0% | — |
| `hybrid` | `ollama:embeddinggemma` | `scoped_filters` | 8 | 99.0% | 100.0% | 100.0% | 83.1% | — |
| `hybrid` | `ollama:embeddinggemma` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_unfloored` | `ollama:qwen3-embedding:0.6b` | `tag_lookup` | 10 | 21.9% | 23.3% | 27.5% | 12.0% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:0.6b` | `exact_lexical` | 10 | 69.8% | 72.0% | 77.5% | 18.0% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:0.6b` | `semantic_paraphrase` | 12 | 84.4% | 86.1% | 91.7% | 20.0% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:0.6b` | `hybrid_intent` | 10 | 93.9% | 100.0% | 90.0% | 32.0% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:0.6b` | `scoped_filters` | 8 | 96.7% | 100.0% | 93.8% | 59.8% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:0.6b` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_floored` | `ollama:qwen3-embedding:0.6b` | `tag_lookup` | 10 | 21.9% | 23.3% | 27.5% | 12.0% | — |
| `embedding_floored` | `ollama:qwen3-embedding:0.6b` | `exact_lexical` | 10 | 69.8% | 72.0% | 77.5% | 18.0% | — |
| `embedding_floored` | `ollama:qwen3-embedding:0.6b` | `semantic_paraphrase` | 12 | 84.4% | 86.1% | 91.7% | 20.0% | — |
| `embedding_floored` | `ollama:qwen3-embedding:0.6b` | `hybrid_intent` | 10 | 93.9% | 100.0% | 90.0% | 32.0% | — |
| `embedding_floored` | `ollama:qwen3-embedding:0.6b` | `scoped_filters` | 8 | 96.7% | 100.0% | 93.8% | 59.8% | — |
| `embedding_floored` | `ollama:qwen3-embedding:0.6b` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `hybrid` | `ollama:qwen3-embedding:0.6b` | `tag_lookup` | 10 | 91.0% | 100.0% | 76.7% | 38.0% | — |
| `hybrid` | `ollama:qwen3-embedding:0.6b` | `exact_lexical` | 10 | 96.1% | 100.0% | 95.0% | 26.0% | — |
| `hybrid` | `ollama:qwen3-embedding:0.6b` | `semantic_paraphrase` | 12 | 84.4% | 86.1% | 91.7% | 20.0% | — |
| `hybrid` | `ollama:qwen3-embedding:0.6b` | `hybrid_intent` | 10 | 90.9% | 95.0% | 92.5% | 34.0% | — |
| `hybrid` | `ollama:qwen3-embedding:0.6b` | `scoped_filters` | 8 | 96.7% | 100.0% | 93.8% | 59.8% | — |
| `hybrid` | `ollama:qwen3-embedding:0.6b` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_unfloored` | `ollama:qwen3-embedding:4b` | `tag_lookup` | 10 | 22.1% | 21.7% | 30.0% | 12.0% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:4b` | `exact_lexical` | 10 | 65.6% | 65.0% | 70.0% | 16.0% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:4b` | `semantic_paraphrase` | 12 | 89.7% | 86.1% | 100.0% | 21.7% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:4b` | `hybrid_intent` | 10 | 89.3% | 100.0% | 74.2% | 26.0% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:4b` | `scoped_filters` | 8 | 97.5% | 100.0% | 100.0% | 62.3% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:4b` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_floored` | `ollama:qwen3-embedding:4b` | `tag_lookup` | 10 | 22.1% | 21.7% | 30.0% | 12.0% | — |
| `embedding_floored` | `ollama:qwen3-embedding:4b` | `exact_lexical` | 10 | 65.6% | 65.0% | 70.0% | 16.0% | — |
| `embedding_floored` | `ollama:qwen3-embedding:4b` | `semantic_paraphrase` | 12 | 89.7% | 86.1% | 100.0% | 21.7% | — |
| `embedding_floored` | `ollama:qwen3-embedding:4b` | `hybrid_intent` | 10 | 89.3% | 100.0% | 74.2% | 26.0% | — |
| `embedding_floored` | `ollama:qwen3-embedding:4b` | `scoped_filters` | 8 | 97.5% | 100.0% | 100.0% | 63.3% | — |
| `embedding_floored` | `ollama:qwen3-embedding:4b` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `hybrid` | `ollama:qwen3-embedding:4b` | `tag_lookup` | 10 | 90.0% | 100.0% | 74.2% | 36.0% | — |
| `hybrid` | `ollama:qwen3-embedding:4b` | `exact_lexical` | 10 | 97.7% | 100.0% | 100.0% | 28.0% | — |
| `hybrid` | `ollama:qwen3-embedding:4b` | `semantic_paraphrase` | 12 | 89.7% | 86.1% | 100.0% | 21.7% | — |
| `hybrid` | `ollama:qwen3-embedding:4b` | `hybrid_intent` | 10 | 87.1% | 95.0% | 74.2% | 26.0% | — |
| `hybrid` | `ollama:qwen3-embedding:4b` | `scoped_filters` | 8 | 98.6% | 100.0% | 100.0% | 63.3% | — |
| `hybrid` | `ollama:qwen3-embedding:4b` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |

## Breakdown by Query Category (`top_n=10`)

| Mode | Embedding | Category | Queries | nDCG@10 | MRR@10 | Recall@10 | Precision@10 | Abstention Rate |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `random` | `none` | `tag_lookup` | 10 | 3.1% | 3.1% | 7.3% | 3.0% | — |
| `random` | `none` | `exact_lexical` | 10 | 6.3% | 5.0% | 10.0% | 1.0% | — |
| `random` | `none` | `semantic_paraphrase` | 12 | 0.0% | 0.0% | 0.0% | 0.0% | — |
| `random` | `none` | `hybrid_intent` | 10 | 7.5% | 5.4% | 17.5% | 3.0% | — |
| `random` | `none` | `scoped_filters` | 8 | 72.5% | 72.9% | 83.3% | 50.9% | — |
| `random` | `none` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `keyword_only` | `none` | `tag_lookup` | 10 | 89.0% | 100.0% | 71.7% | 87.1% | — |
| `keyword_only` | `none` | `exact_lexical` | 10 | 88.3% | 90.0% | 85.0% | 90.0% | — |
| `keyword_only` | `none` | `semantic_paraphrase` | 12 | 0.0% | 0.0% | 0.0% | 0.0% | — |
| `keyword_only` | `none` | `hybrid_intent` | 10 | 32.5% | 35.0% | 30.0% | 21.7% | — |
| `keyword_only` | `none` | `scoped_filters` | 8 | 80.5% | 87.5% | 75.0% | 87.5% | — |
| `keyword_only` | `none` | `unanswerable_negative` | 10 | — | — | — | — | 90.0% |
| `embedding_unfloored` | `gemini:gemini-embedding-001` | `tag_lookup` | 10 | 69.0% | 73.3% | 72.7% | 17.0% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-001` | `exact_lexical` | 10 | 86.7% | 85.8% | 95.0% | 12.0% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-001` | `semantic_paraphrase` | 12 | 96.5% | 95.8% | 100.0% | 10.8% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-001` | `hybrid_intent` | 10 | 93.5% | 100.0% | 90.0% | 17.0% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-001` | `scoped_filters` | 8 | 99.4% | 100.0% | 100.0% | 54.6% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-001` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_floored` | `gemini:gemini-embedding-001` | `tag_lookup` | 10 | 69.0% | 73.3% | 72.7% | 17.0% | — |
| `embedding_floored` | `gemini:gemini-embedding-001` | `exact_lexical` | 10 | 86.7% | 85.8% | 95.0% | 12.0% | — |
| `embedding_floored` | `gemini:gemini-embedding-001` | `semantic_paraphrase` | 12 | 96.5% | 95.8% | 100.0% | 10.8% | — |
| `embedding_floored` | `gemini:gemini-embedding-001` | `hybrid_intent` | 10 | 93.5% | 100.0% | 90.0% | 17.0% | — |
| `embedding_floored` | `gemini:gemini-embedding-001` | `scoped_filters` | 8 | 99.4% | 100.0% | 100.0% | 54.6% | — |
| `embedding_floored` | `gemini:gemini-embedding-001` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `hybrid` | `gemini:gemini-embedding-001` | `tag_lookup` | 10 | 95.6% | 100.0% | 90.0% | 22.0% | — |
| `hybrid` | `gemini:gemini-embedding-001` | `exact_lexical` | 10 | 100.0% | 100.0% | 100.0% | 14.0% | — |
| `hybrid` | `gemini:gemini-embedding-001` | `semantic_paraphrase` | 12 | 96.5% | 95.8% | 100.0% | 10.8% | — |
| `hybrid` | `gemini:gemini-embedding-001` | `hybrid_intent` | 10 | 89.3% | 95.0% | 87.5% | 16.0% | — |
| `hybrid` | `gemini:gemini-embedding-001` | `scoped_filters` | 8 | 99.4% | 100.0% | 100.0% | 54.6% | — |
| `hybrid` | `gemini:gemini-embedding-001` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_unfloored` | `gemini:gemini-embedding-2` | `tag_lookup` | 10 | 67.7% | 74.3% | 76.0% | 18.0% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-2` | `exact_lexical` | 10 | 78.1% | 76.4% | 82.5% | 10.0% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-2` | `semantic_paraphrase` | 12 | 99.5% | 100.0% | 100.0% | 10.8% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-2` | `hybrid_intent` | 10 | 94.1% | 100.0% | 87.5% | 16.0% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-2` | `scoped_filters` | 8 | 100.0% | 100.0% | 100.0% | 54.6% | — |
| `embedding_unfloored` | `gemini:gemini-embedding-2` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_floored` | `gemini:gemini-embedding-2` | `tag_lookup` | 10 | 67.7% | 74.3% | 76.0% | 18.0% | — |
| `embedding_floored` | `gemini:gemini-embedding-2` | `exact_lexical` | 10 | 78.1% | 76.4% | 82.5% | 10.0% | — |
| `embedding_floored` | `gemini:gemini-embedding-2` | `semantic_paraphrase` | 12 | 99.5% | 100.0% | 100.0% | 10.8% | — |
| `embedding_floored` | `gemini:gemini-embedding-2` | `hybrid_intent` | 10 | 94.1% | 100.0% | 87.5% | 16.0% | — |
| `embedding_floored` | `gemini:gemini-embedding-2` | `scoped_filters` | 8 | 100.0% | 100.0% | 100.0% | 54.6% | — |
| `embedding_floored` | `gemini:gemini-embedding-2` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `hybrid` | `gemini:gemini-embedding-2` | `tag_lookup` | 10 | 95.0% | 100.0% | 90.0% | 22.0% | — |
| `hybrid` | `gemini:gemini-embedding-2` | `exact_lexical` | 10 | 99.6% | 100.0% | 100.0% | 14.0% | — |
| `hybrid` | `gemini:gemini-embedding-2` | `semantic_paraphrase` | 12 | 99.5% | 100.0% | 100.0% | 10.8% | — |
| `hybrid` | `gemini:gemini-embedding-2` | `hybrid_intent` | 10 | 93.9% | 100.0% | 87.5% | 16.0% | — |
| `hybrid` | `gemini:gemini-embedding-2` | `scoped_filters` | 8 | 100.0% | 100.0% | 100.0% | 54.6% | — |
| `hybrid` | `gemini:gemini-embedding-2` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_unfloored` | `openai:text-embedding-3-small` | `tag_lookup` | 10 | 54.7% | 61.4% | 59.0% | 13.0% | — |
| `embedding_unfloored` | `openai:text-embedding-3-small` | `exact_lexical` | 10 | 78.7% | 82.0% | 87.5% | 12.0% | — |
| `embedding_unfloored` | `openai:text-embedding-3-small` | `semantic_paraphrase` | 12 | 96.9% | 95.8% | 100.0% | 10.8% | — |
| `embedding_unfloored` | `openai:text-embedding-3-small` | `hybrid_intent` | 10 | 91.1% | 100.0% | 80.8% | 14.0% | — |
| `embedding_unfloored` | `openai:text-embedding-3-small` | `scoped_filters` | 8 | 99.0% | 100.0% | 100.0% | 54.6% | — |
| `embedding_unfloored` | `openai:text-embedding-3-small` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_floored` | `openai:text-embedding-3-small` | `tag_lookup` | 10 | 53.4% | 61.4% | 54.0% | 33.2% | — |
| `embedding_floored` | `openai:text-embedding-3-small` | `exact_lexical` | 10 | 73.5% | 80.0% | 72.5% | 32.0% | — |
| `embedding_floored` | `openai:text-embedding-3-small` | `semantic_paraphrase` | 12 | 96.9% | 95.8% | 100.0% | 42.3% | — |
| `embedding_floored` | `openai:text-embedding-3-small` | `hybrid_intent` | 10 | 91.1% | 100.0% | 80.8% | 15.5% | — |
| `embedding_floored` | `openai:text-embedding-3-small` | `scoped_filters` | 8 | 75.4% | 87.5% | 68.8% | 82.5% | — |
| `embedding_floored` | `openai:text-embedding-3-small` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `hybrid` | `openai:text-embedding-3-small` | `tag_lookup` | 10 | 92.4% | 100.0% | 81.7% | 48.2% | — |
| `hybrid` | `openai:text-embedding-3-small` | `exact_lexical` | 10 | 96.6% | 100.0% | 95.0% | 37.3% | — |
| `hybrid` | `openai:text-embedding-3-small` | `semantic_paraphrase` | 12 | 96.9% | 95.8% | 100.0% | 42.3% | — |
| `hybrid` | `openai:text-embedding-3-small` | `hybrid_intent` | 10 | 87.8% | 95.0% | 80.8% | 15.5% | — |
| `hybrid` | `openai:text-embedding-3-small` | `scoped_filters` | 8 | 97.6% | 100.0% | 93.8% | 95.0% | — |
| `hybrid` | `openai:text-embedding-3-small` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_unfloored` | `ollama:embeddinggemma` | `tag_lookup` | 10 | 52.9% | 54.8% | 75.0% | 16.0% | — |
| `embedding_unfloored` | `ollama:embeddinggemma` | `exact_lexical` | 10 | 60.2% | 58.1% | 67.5% | 8.0% | — |
| `embedding_unfloored` | `ollama:embeddinggemma` | `semantic_paraphrase` | 12 | 96.4% | 95.8% | 100.0% | 10.8% | — |
| `embedding_unfloored` | `ollama:embeddinggemma` | `hybrid_intent` | 10 | 91.1% | 100.0% | 81.7% | 14.0% | — |
| `embedding_unfloored` | `ollama:embeddinggemma` | `scoped_filters` | 8 | 99.0% | 100.0% | 100.0% | 54.6% | — |
| `embedding_unfloored` | `ollama:embeddinggemma` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_floored` | `ollama:embeddinggemma` | `tag_lookup` | 10 | 52.9% | 54.8% | 75.0% | 16.0% | — |
| `embedding_floored` | `ollama:embeddinggemma` | `exact_lexical` | 10 | 54.6% | 55.0% | 55.0% | 8.2% | — |
| `embedding_floored` | `ollama:embeddinggemma` | `semantic_paraphrase` | 12 | 96.4% | 95.8% | 100.0% | 17.3% | — |
| `embedding_floored` | `ollama:embeddinggemma` | `hybrid_intent` | 10 | 91.1% | 100.0% | 81.7% | 14.0% | — |
| `embedding_floored` | `ollama:embeddinggemma` | `scoped_filters` | 8 | 94.2% | 100.0% | 93.8% | 82.3% | — |
| `embedding_floored` | `ollama:embeddinggemma` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `hybrid` | `ollama:embeddinggemma` | `tag_lookup` | 10 | 94.0% | 100.0% | 90.0% | 22.0% | — |
| `hybrid` | `ollama:embeddinggemma` | `exact_lexical` | 10 | 94.6% | 95.0% | 95.0% | 16.8% | — |
| `hybrid` | `ollama:embeddinggemma` | `semantic_paraphrase` | 12 | 96.4% | 95.8% | 100.0% | 17.3% | — |
| `hybrid` | `ollama:embeddinggemma` | `hybrid_intent` | 10 | 88.2% | 95.0% | 81.7% | 14.0% | — |
| `hybrid` | `ollama:embeddinggemma` | `scoped_filters` | 8 | 99.0% | 100.0% | 100.0% | 82.3% | — |
| `hybrid` | `ollama:embeddinggemma` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_unfloored` | `ollama:qwen3-embedding:0.6b` | `tag_lookup` | 10 | 24.5% | 24.8% | 37.0% | 9.0% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:0.6b` | `exact_lexical` | 10 | 69.8% | 72.0% | 77.5% | 9.0% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:0.6b` | `semantic_paraphrase` | 12 | 87.2% | 87.3% | 100.0% | 10.8% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:0.6b` | `hybrid_intent` | 10 | 94.6% | 100.0% | 92.5% | 17.0% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:0.6b` | `scoped_filters` | 8 | 98.0% | 100.0% | 100.0% | 54.6% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:0.6b` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_floored` | `ollama:qwen3-embedding:0.6b` | `tag_lookup` | 10 | 24.5% | 24.8% | 37.0% | 9.0% | — |
| `embedding_floored` | `ollama:qwen3-embedding:0.6b` | `exact_lexical` | 10 | 69.8% | 72.0% | 77.5% | 9.0% | — |
| `embedding_floored` | `ollama:qwen3-embedding:0.6b` | `semantic_paraphrase` | 12 | 87.2% | 87.3% | 100.0% | 10.8% | — |
| `embedding_floored` | `ollama:qwen3-embedding:0.6b` | `hybrid_intent` | 10 | 94.6% | 100.0% | 92.5% | 17.0% | — |
| `embedding_floored` | `ollama:qwen3-embedding:0.6b` | `scoped_filters` | 8 | 98.0% | 100.0% | 100.0% | 54.6% | — |
| `embedding_floored` | `ollama:qwen3-embedding:0.6b` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `hybrid` | `ollama:qwen3-embedding:0.6b` | `tag_lookup` | 10 | 91.7% | 100.0% | 81.7% | 20.0% | — |
| `hybrid` | `ollama:qwen3-embedding:0.6b` | `exact_lexical` | 10 | 96.1% | 100.0% | 95.0% | 13.0% | — |
| `hybrid` | `ollama:qwen3-embedding:0.6b` | `semantic_paraphrase` | 12 | 87.2% | 87.3% | 100.0% | 10.8% | — |
| `hybrid` | `ollama:qwen3-embedding:0.6b` | `hybrid_intent` | 10 | 91.5% | 95.0% | 95.0% | 18.0% | — |
| `hybrid` | `ollama:qwen3-embedding:0.6b` | `scoped_filters` | 8 | 98.0% | 100.0% | 100.0% | 54.6% | — |
| `hybrid` | `ollama:qwen3-embedding:0.6b` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_unfloored` | `ollama:qwen3-embedding:4b` | `tag_lookup` | 10 | 31.8% | 25.2% | 57.0% | 12.0% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:4b` | `exact_lexical` | 10 | 65.6% | 65.0% | 70.0% | 8.0% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:4b` | `semantic_paraphrase` | 12 | 89.7% | 86.1% | 100.0% | 10.8% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:4b` | `hybrid_intent` | 10 | 91.8% | 100.0% | 86.7% | 16.0% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:4b` | `scoped_filters` | 8 | 97.5% | 100.0% | 100.0% | 54.6% | — |
| `embedding_unfloored` | `ollama:qwen3-embedding:4b` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `embedding_floored` | `ollama:qwen3-embedding:4b` | `tag_lookup` | 10 | 31.8% | 25.2% | 57.0% | 12.0% | — |
| `embedding_floored` | `ollama:qwen3-embedding:4b` | `exact_lexical` | 10 | 65.6% | 65.0% | 70.0% | 8.0% | — |
| `embedding_floored` | `ollama:qwen3-embedding:4b` | `semantic_paraphrase` | 12 | 89.7% | 86.1% | 100.0% | 10.8% | — |
| `embedding_floored` | `ollama:qwen3-embedding:4b` | `hybrid_intent` | 10 | 91.8% | 100.0% | 86.7% | 16.0% | — |
| `embedding_floored` | `ollama:qwen3-embedding:4b` | `scoped_filters` | 8 | 97.5% | 100.0% | 100.0% | 56.2% | — |
| `embedding_floored` | `ollama:qwen3-embedding:4b` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
| `hybrid` | `ollama:qwen3-embedding:4b` | `tag_lookup` | 10 | 91.5% | 100.0% | 81.7% | 20.0% | — |
| `hybrid` | `ollama:qwen3-embedding:4b` | `exact_lexical` | 10 | 97.7% | 100.0% | 100.0% | 14.0% | — |
| `hybrid` | `ollama:qwen3-embedding:4b` | `semantic_paraphrase` | 12 | 89.7% | 86.1% | 100.0% | 10.8% | — |
| `hybrid` | `ollama:qwen3-embedding:4b` | `hybrid_intent` | 10 | 89.5% | 95.0% | 86.7% | 16.0% | — |
| `hybrid` | `ollama:qwen3-embedding:4b` | `scoped_filters` | 8 | 98.6% | 100.0% | 100.0% | 56.2% | — |
| `hybrid` | `ollama:qwen3-embedding:4b` | `unanswerable_negative` | 10 | — | — | — | — | 0.0% |
