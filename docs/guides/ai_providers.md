# Choosing an AI Provider

Every AI feature in Open Private Cloud is optional. You can run the server with zero AI (just fast Private Cloud sync, the Web UI, tasks, and native keyword search), connect Google Gemini for the highest accuracy and speed, or point it at a local model server on your own hardware so your notes never leave your network.

## Three ways to run

| Setup | Best for | What you need |
| :--- | :--- | :--- |
| **Google Gemini (recommended default)** | Highest handwriting accuracy, Bullet Journal symbols, diagrams, and best hybrid search embedding quality | `SUPERNOTE_GEMINI_API_KEY` (Paid tier does not train on API data; Free tier does—see below) |
| **100% Local (Ollama, vLLM, llama.cpp, LM Studio)** | Keeping every note and image strictly inside your home network | A local OpenAI-compatible vision model for OCR/summaries and `embeddinggemma` for search |
| **No AI (sync only)** | Minimal ~135–160 MB Private Cloud sync on a Raspberry Pi or NAS | Nothing; run `supernote serve` |

You can also mix providers per capability (for example, Gemini for OCR and a local Ollama server for summaries and embeddings).

## Benchmark summary

We maintain reproducible benchmarks on real Supernote `.note` pages rather than relying on marketing claims.

<p align="center">
  <img src="../../evals/ocr/pareto_frontier.svg" alt="OCR Quality vs. Latency Pareto Frontier" width="840">
</p>

### Handwriting & Bullet Journal OCR

Across 30 `.note` pages (Bullet Journal Rapid Logging, two-column diagrams and guitar tablature, French/Spanish/Turkish notes, overlapping strokes, and synthetic fixtures; full category breakdown in [evals/ocr/RESULTS.md](../../evals/ocr/RESULTS.md)):

| Provider / Model | Pages | Word F1 | Mean CER | Content CER | Handwritten BuJo Symbols | All BuJo Symbols | Median Latency |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `Gemini 3.5 Flash-Lite` *(default)* | 30 | 99.0% | 2.3% | 1.4% | 85.5% | 95.8% | 1.18 s |
| `Gemini 3.6 Flash` | 30 | 99.7% | 4.2% | 3.6% | 90.5% | 97.3% | 6.63 s |
| `Gemini 3.8 Flash` | 30 | 96.5% | 5.6% | 5.4% | 90.5% | 97.3% | 9.93 s |
| `Supernote On-Device` (`MyScript iink 4.1.0`) | 25 | 75.5% | 17.2% | 16.7% | 18.6% | 18.6% | 0.91 s |
| `Apple Vision Accurate` | 30 | 73.7% | 21.7% | 20.7% | 4.5% | 49.7% | 0.41 s |
| `Apple Vision Fast` | 30 | 17.8% | 72.8% | 70.7% | 0.0% | 8.7% | 0.13 s |

`gemini-3.5-flash-lite` is the easiest option that works well out of the box: it reads nearly every word accurately (99.0% Word F1, 0.0% median CER) in ~1.2 s per page for under `$0.001` per page while preserving Bullet Journal symbols, nested indentation, and strikethroughs.

If you want to stay fully local, you have two main paths with clear tradeoffs. On macOS, Apple Vision (`vision-accurate`) handles basic English prose fine (93.0% Word F1 on plain prose) with no model server, though it cannot take prompts so it drops Bullet Journal symbols and struggles with multi-column layouts. Local vision or dedicated OCR models (such as DeepSeek-OCR or GLM-OCR) keep everything on your own hardware, though they often need extra tuning—like setting `prompt_override` to their expected native instruction (see the [Dedicated local OCR example](#dedicated-local-ocr-models-deepseek-ocr-glm-ocr) below).

### Hybrid search & embeddings

Across 100 pages in 26 notebooks and 60 blind ground-truth queries (`#tag` lookups, exact IDs, typos, CJK, paraphrases, and unanswerable negatives; full breakdown in [evals/search/RESULTS.md](../../evals/search/RESULTS.md)):

| Mode | Embedding Model | nDCG@5 | MRR@5 | Recall@5 | nDCG@10 | Recall@10 | Median Latency |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `hybrid` *(recommended cloud)* | `gemini:gemini-embedding-2` | **97.1%** | **100.0%** | **93.7%** | **97.6%** | **95.5%** | 68.8 ms |
| `hybrid` | `gemini:gemini-embedding-001` | 95.5% | 98.0% | 93.2% | 96.0% | 95.5% | 69.4 ms |
| `hybrid` | `openai:text-embedding-3-small` | 94.0% | 98.0% | 89.5% | 94.2% | 90.5% | 50.9 ms |
| `hybrid` *(recommended local)* | `ollama:embeddinggemma` | **93.7%** | **97.0%** | **90.2%** | **94.3%** | **93.3%** | **23.5 ms** |
| `hybrid` | `ollama:qwen3-embedding:4b` | 92.2% | 95.7% | 89.7% | 93.0% | 93.7% | 58.9 ms |
| `hybrid` | `ollama:qwen3-embedding:0.6b` | 91.3% | 95.7% | 89.8% | 92.5% | 94.3% | 28.9 ms |
| `keyword_only` | `none` | 54.8% | 59.0% | 49.3% | 54.8% | 49.3% | 4.0 ms |

### Public multimodal benchmarks (Gemini vs. Claude)

For broader context on why Gemini is the default multimodal backend (Anthropic Claude is not a built-in server provider), here are recent results (Jun–Nov 2026) from [Artificial Analysis](https://artificialanalysis.ai/) (`MMMU-Pro`), [Vals AI](https://www.vals.ai/benchmarks) (`MMMU-Pro` and `MortgageTax` scanned-form extraction), and [LMArena Vision](https://lmarena.ai/):

| Model | Release | API Price (In / Out per 1M) | LMArena Vision (Elo) | MMMU-Pro (AA) | MMMU-Pro (Vals) | MortgageTax (Vals) |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: |
| `Gemini 3.5 Flash-Lite` | Jul 2026 | `$0.30 / $2.50` | 1268 | 79.0% | 83.6% | 68.7% |
| `Claude Haiku 5.5` | Oct 2026 | `$0.10 / $0.50` (≤100k) | — | — | — | — |
| `Gemini 3.6 Flash` | Jul 2026 | `$0.75 / $3.75`\* | 1297 | 83.2% | 88.4% | 67.6% |
| `Gemini 3.8 Flash` | Sep 2026 | `$0.75 / $3.75`\* | 1316 | 85.6% | 89.1% | 65.3% |
| `Claude Sonnet 5` | Jun 2026 | `$2.00 / $10.00` | 1272 | 77.3% | 83.0% | 70.0% |
| `Claude Sonnet 5.5` | Sep 2026 | `$2.00 / $10.00` | 1283 | — | — | — |
| `Gemini 4 Carbon` | Oct 2026 | `$4.00 / $20.00` | — | 89.3% | — | — |
| `Claude Opus 5` | Jul 2026 | `$5.00 / $25.00` | 1317 | 84.7% | 89.9% | 72.1% |
| `Claude Opus 5.5` | Sep 2026 | `$4.00 / $20.00` | 1324 | 87.7% | — | — |

*\*Promotional rate through Dec 31, 2026 (`$1.50 / $7.50` standard; 50% lower via Batch API).*

## API data use, training, and retention

Google Gemini offers both a **Free tier** that trains on API data and a **Paid tier** (enabled by linking a [Cloud Billing account](https://aistudio.google.com/docs/terms#paid-services) to your Google AI Studio project) that does not. Commercial API traffic on OpenAI and Anthropic is excluded from training by default:

| Provider & Tier | Used to Train Models? | Default API Log Retention | Policy Citations |
| :--- | :--- | :--- | :--- |
| **Gemini API (Paid tier)** | **No** (Google acts as Data Processor) | Abuse monitoring; optional AI Studio project logs default to 55 days (configurable to 7 days or off; [ZDR](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/zero-data-retention) on Enterprise/Vertex AI) | [Paid Services Terms](https://aistudio.google.com/docs/terms#data-use-paid), [Logs Policy](https://aistudio.google.com/docs/logs-policy), [Google DPA](https://business.safety.google/processorterms/) |
| **Gemini API (Free tier)** | **Yes** (outside EEA, UK, and Switzerland; includes human review) | Retained for product improvement (avoid for private or sensitive notes) | [Unpaid Services Terms](https://aistudio.google.com/docs/terms#data-use-unpaid) |
| **OpenAI API** (`api.openai.com`) | **No** (unless opted in) | Up to 30 days for abuse monitoring; ZDR available for eligible orgs | [OpenAI Data Controls](https://developers.openai.com/api/docs/guides/your-data) |
| **Anthropic Claude API** (`api.anthropic.com`) | **No** under Commercial Terms | Not retained by default on standard endpoints, or up to 30 days on covered models; ZDR available | [Commercial Terms](https://www.anthropic.com/legal/commercial-terms), [Training Policy](https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training), [Data Retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention) |
| **Local models** (`Ollama`, `llama.cpp`, `vLLM`, `apple`) | **No** | Local only; notes never leave your server | — |

## Configuration examples

### Google Gemini (default)

Set `SUPERNOTE_GEMINI_API_KEY` and start the server. That enables `gemini-3.5-flash-lite` for OCR/summaries and `gemini-embedding-2` for hybrid search automatically.

### 100% local with Ollama

Run OCR, summaries, and hybrid search embeddings entirely on your own machine:

```yaml
ai:
  providers:
    ollama:
      type: openai
      base_url: "http://localhost:11434/v1"

  ocr:
    provider: ollama
    model: gemma3:27b
    max_concurrency: 1

  summary:
    provider: ollama
    model: gemma3:27b
    max_concurrency: 1

  embedding:
    provider: ollama
    model: embeddinggemma
    max_concurrency: 2
```

When running Open Private Cloud in Docker and Ollama on your host, set `base_url: "http://host.docker.internal:11434/v1"` (on Linux, also pass `--add-host=host.docker.internal:host-gateway`). `gemma3:27b` needs ~18–20 GB of VRAM or unified memory; on smaller machines, swap in a lighter vision model like `gemma3:12b` or `qwen2.5vl:7b` (expect lower handwriting accuracy on dense notes than Gemini).

### Mixing cloud and local models

You can configure `ocr`, `summary`, and `embedding` independently in `config/config.yaml`:

```yaml
ai:
  providers:
    gemini:
      api_key: "AIzaSyYourGeminiKey"
    ollama:
      type: openai
      base_url: "http://localhost:11434/v1"

  ocr:
    provider: gemini
    model: gemini-3.5-flash-lite
    max_concurrency: 5

  summary:
    provider: ollama
    model: gemma3:27b
    max_concurrency: 1

  embedding:
    provider: ollama
    model: embeddinggemma
    max_concurrency: 2
```

### Multiple local servers

Give each server its own name under `ai.providers` with `type: openai`:

```yaml
ai:
  providers:
    ollama:
      type: openai
      base_url: "http://localhost:11434/v1"
    llamacpp:
      type: openai
      base_url: "http://localhost:8082/v1"
  summary:
    provider: ollama
    model: gemma3:27b
  embedding:
    provider: llamacpp
    model: embeddinggemma
```

### Dedicated local OCR models (DeepSeek-OCR, GLM-OCR)

Dedicated OCR models are often trained on a single short instruction rather than a multi-part Bullet Journal prompt. Use `prompt_override` to send their native prompt instead:

```yaml
ai:
  providers:
    local:
      type: openai
      base_url: "http://localhost:8000/v1"
  ocr:
    provider: local
    model: DeepSeek-OCR-8bit
    max_concurrency: 1
    prompt_override: "Convert the document to markdown."
```

### macOS Apple Vision (offline fallback)

On macOS (`pip install "supernote[server,apple]"`), Apple's built-in `Vision` framework (`vision-accurate`) works offline for plain English prose without a GPU or API key. Avoid `vision-fast`, which only detects printed text, and note that Vision cannot follow prompts for diagrams or Bullet Journal symbols:

```yaml
ai:
  ocr:
    provider: apple
    model: vision-accurate
    max_concurrency: 2
```

See the [Configuration Reference](../reference/configuration.md) for all `ai` settings and environment variables.
