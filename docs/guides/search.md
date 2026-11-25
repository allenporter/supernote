# Search & Retrieval

You can search across all of your synced `.note` notebooks and standalone images from the Web UI (`Cmd/Ctrl+K`), the CLI (`supernote cloud search`), or an AI assistant connected over MCP.

With no AI configured, search matches the native page keywords you tag on your Supernote tablet (plus any existing OCR transcripts). When you add an OCR provider and an embedding model, it automatically upgrades to hybrid search across your full handwritten text, combining exact keyword matching with semantic similarity.

## Keyword search vs. hybrid search

| Mode | Requires AI? | Best for | Typical speed |
| :--- | :---: | :--- | :--- |
| Keyword search (default) | No | Native Supernote page keywords, exact words in transcripts, `#tags`, filenames, and date filters | ~4 ms |
| Hybrid search (keyword + embeddings) | Optional (cloud or local) | Concept queries using different wording (*"backyard drainage sketch"*), paraphrases, and multilingual notes | ~24–69 ms |

In hybrid mode, the server runs both keyword matching and vector search and merges the results. Exact `#tags` and names still rank at the top, while natural-language questions can still find pages that never used your exact search terms.

## Picking an embedding model

We benchmarked cloud and local embedding models across 100 notebook pages and 60 queries in [evals/search/RESULTS.md](../../evals/search/RESULTS.md):

- **Google Gemini (`gemini-embedding-2`)** is the recommended cloud default. It scored highest across exact, paraphrase, and multilingual queries (~69 ms median latency) and turns on automatically when you set `SUPERNOTE_GEMINI_API_KEY`.
- **Ollama (`embeddinggemma`)** is the recommended local option. Everything stays on your own machine, latency is ~24 ms, and hybrid accuracy stays close to cloud models.
- **No embedding model** is completely fine if you want zero AI dependencies. You still get fast lexical search over native Supernote page keywords and any existing transcripts.

To use local embeddings with Ollama, add this to `config/config.yaml`:

```yaml
ai:
  openai_servers:
    ollama:
      base_url: "http://localhost:11434/v1"
      api_key: "ollama"
  embedding:
    provider: "openai"
    server: "ollama"
    model: "embeddinggemma"
```

See the [Configuration Reference](../reference/configuration.md) for all provider options.

## Searching in practice

In the Web UI, press `Cmd+K` (macOS) or `Ctrl+K` (Windows/Linux) from any tab to search across notebooks and standalone images, filter by notebook name or date range, and jump directly to the matching page.

From the terminal:

```bash
# Search across all notebooks
supernote cloud search "backyard drainage plan"

# Narrow by notebook name and date range
supernote cloud search "Q2 budget" --name "Work" --start-date 2026-04-01 --end-date 2026-06-30
```

See the [CLI Reference](../reference/cli_reference.md) for all search flags, or the [MCP Guide](./mcp.md) to see how AI assistants use `search_notebook_chunks`.
