# Hybrid Search & Retrieval

Open Private Cloud lets you search across years of handwritten `.note` notebooks and standalone images from the Web UI (`Cmd/Ctrl+K`), the CLI (`supernote cloud search`), and AI assistants via MCP.

Search works **out of the box with zero AI required** using instant lexical matching, and automatically upgrades to **Hybrid Search** (lexical + semantic embeddings) when you configure an embedding model.

---

## Two Ways to Search

| Mode | Requires AI? | Best For | Speed |
| :--- | :---: | :--- | :--- |
| **Keyword Search (Default)** | **No** | Exact phrases, `#tags`, native Supernote page keywords, filenames, IDs, and date filters | ~4 ms |
| **Hybrid Search (Keyword + Embeddings)** | Optional (Cloud or Local) | Conceptual queries with different wording (*"Where did I sketch the backyard drainage plan?"*), paraphrased ideas, and multilingual recall | ~24–69 ms |

When an embedding model is configured, Open Private Cloud runs **both** keyword matching and vector similarity search and merges the results into a single ranked list—so exact `#tags` and IDs never get drowned out by semantic matches, while natural-language questions still find pages that never used your exact search words.

---

## Choosing an Embedding Model

Based on our [100-page, 60-query Search & Embedding Benchmark](../../evals/search/RESULTS.md):

- **Recommended Cloud Default — Google Gemini (`gemini-embedding-2`)**: Highest overall retrieval accuracy across exact, paraphrase, and multilingual queries (~69 ms median latency). Enabled automatically when you set `SUPERNOTE_GEMINI_API_KEY`.
- **Recommended 100% Local — Ollama (`embeddinggemma`)**: Runs entirely on your own hardware with zero external network calls, delivering strong hybrid accuracy at ~24 ms median latency.
- **No Embeddings**: Leave embeddings unconfigured to use fast, zero-cost lexical search over native Supernote page keywords and any existing transcripts.

### Minimal Local Embeddings Example (`Ollama`)

```yaml
# config/config.yaml
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

See the **[Configuration Reference](../reference/configuration.md)** for full provider setup and the **[Search & Embedding Benchmarks](../../evals/search/RESULTS.md)** for the complete comparison across Gemini, OpenAI, and Ollama models.

---

## Searching in Everyday Workflows

### Web UI (`Cmd/Ctrl+K`)
Press `Cmd+K` (macOS) or `Ctrl+K` (Windows/Linux) from any tab to search across notebooks and standalone images, filter by notebook or date window, and jump straight to the matching page.

### Command Line (`supernote cloud search`)
```bash
# Concept search across all notebooks
supernote cloud search "backyard drainage plan"

# Filter by notebook name and date range
supernote cloud search "Q2 budget" --name "Work" --start-date 2026-04-01 --end-date 2026-06-30
```

See the **[CLI Reference](../reference/cli_reference.md)** for all search flags.

### AI Assistants (MCP)
Connected assistants use `search_notebook_chunks` to retrieve ranked snippets with `file_id`, `page_index`, and date metadata—then follow up with `get_notebook_transcript` or `get_page_image` when they need the full page text or original handwriting image. See the **[MCP Guide](./mcp.md)** for details.
