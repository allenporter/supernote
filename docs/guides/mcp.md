# MCP Server & AI Assistants

Open Private Cloud includes an optional [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server (`mcp_enabled: true` by default) on port `8081` (`/mcp`). It lets AI assistants like Claude Desktop, Claude Code, Cursor, or custom scripts search your notebooks, read transcripts, inspect hand-drawn diagrams as PNG images, manage Supernote tasks, poll sync events, and update your LLM Wiki.

If you don't need AI assistant access, disable it with `SUPERNOTE_MCP_ENABLED=false` (or `mcp_enabled: false` in `config/config.yaml`). For OCR setup, search, or model benchmarks, see [Handwriting OCR & Multimodal Workflows](./ocr_and_multimodal.md), [Search & Retrieval](./search.md), and [Choosing an AI Provider](./ai_providers.md).

## What an assistant can do

A typical workflow with Claude or Cursor looks like this:

1. Search across your notebooks with `search_notebook_chunks` (or browse recent files with `list_notebooks`).
2. Read full page text with `get_notebook_transcript`.
3. Call `get_page_image(file_id, page_index)` when you want a vision-capable assistant to look directly at a hand-drawn diagram, floor plan, or whiteboard photo.
4. Create or update Supernote To-Do items (`create_task`, `update_task`) or read and edit your compiled [LLM Wiki](./llm_wiki.md) (`search_wiki`, `read_wiki_page`, `upsert_wiki_page`).

## Connecting your client

Open Private Cloud supports two authentication modes:

- **OAuth 2.1 (browser login)** for interactive desktop and web clients (Claude Desktop, Cursor, ChatGPT). The server exposes OAuth discovery on port `8080` and your MCP endpoint on `http://<your-server>:8081/mcp`.
- **Static API keys (`sn_...`)** for headless CLIs, Claude Code, or scripts where a browser login flow isn't convenient.

### Create a static API key (for CLI / headless clients)

```bash
# Log in once interactively
supernote cloud login you@example.com --url http://localhost:8080

# Mint a revocable API key (the secret is shown once)
supernote cloud keys create "claude-code" --expires-days 90

# List or revoke keys at any time
supernote cloud keys list
supernote cloud keys revoke <key-id>
```

You can also manage API keys and connected OAuth clients from the Web UI under account settings.

### Claude Code

```bash
claude mcp add --transport http supernote http://localhost:8081/mcp \
  --header "Authorization: Bearer sn_your_api_key_here"
```

### Claude Desktop & Cursor (`mcp-remote` or native Streamable HTTP)

For clients that connect over Streamable HTTP with OAuth 2.1, point the client at `http://<your-server>:8081/mcp` (or your HTTPS reverse-proxy URL—make sure `base_url` and `mcp_base_url` are set in `config/config.yaml` when running behind Caddy or Nginx).

To use a static API key in `claude_desktop_config.json` via `mcp-remote`:

```json
{
  "mcpServers": {
    "supernote": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://localhost:8081/mcp",
        "--header",
        "Authorization: Bearer sn_your_api_key_here"
      ]
    }
  }
}
```

See the [Configuration Reference](../reference/configuration.md) for `mcp_port`, `mcp_base_url`, `base_url`, and reverse-proxy headers.

## Available MCP tools

All tools scope queries strictly to the authenticated user's account.

### Notebooks, search, and page images

| Tool | Purpose | Key arguments |
| :--- | :--- | :--- |
| `list_notebooks` | List active `.note` notebooks ordered by most recently updated. | `limit=20`, `name_filter` |
| `search_notebook_chunks` | Hybrid search combining native `#keyword` tags, OCR transcripts, and vector embeddings (when configured). | `query`, `top_n=5`, `name_filter`, `date_after`, `date_before` |
| `get_notebook_transcript` | Return the full OCR Markdown transcript for a notebook or a 0-based page slice. | `file_id`, `start_index`, `end_index` |
| `get_page_image` | Return a normalized PNG image (`ImageContent`) for a `.note` page or standalone image so vision models can inspect sketches and diagrams. | `file_id`, `page_index=0`, `max_dimension=1568` (`64`–`2048`) |

### Tasks & schedule

- `list_tasks(group_id=None, include_completed=False, file_id=None)`: List task groups and tasks, optionally filtered by group, completion state, or linked notebook.
- `create_task(title, detail=None, status=None, importance=None, due_time=None, group_id=None, linked_file_id=None, linked_file_path=None, linked_page_id=None, linked_page_number=None, cause_seq=None, reason=None)`: Create a Supernote task, optionally deep-linked to a notebook page.
- `update_task(task_id, ..., clear_link=False, cause_seq=None, reason=None)`: Update task fields, completion state, or page deep-links.
- `delete_task(task_id, cause_seq=None, reason=None)`: Delete a task.

### Domain event feed

- `list_events(sync_token=None, event_types=None, file_id=None, exclude_actors=None, limit=200)`: Poll your account's incremental domain event log (for example `event_types=["note.*", "schedule.*"]`), with cursor pagination via `sync_token` and `"self"` echo suppression via `exclude_actors`.

### LLM Wiki tools (when `wiki.enabled: true`)

When the opt-in [LLM Wiki](./llm_wiki.md) is enabled, eight additional tools are registered:

- `get_wiki_index(limit=100)` and `list_wiki_pages(page_kind=None, limit=50, offset=0)`: Browse active wiki pages with low token overhead.
- `read_wiki_page(slug)`: Read a page's full Markdown body, aliases, backlinks, version, edit policy, and source citations.
- `search_wiki(query, top_k=10)`: Search wiki titles, aliases, summaries, and bodies with 1-hop links and source snippets.
- `upsert_wiki_page(slug, title, body_md, ...)`: Create or update a wiki page using optimistic concurrency (`expected_version`). Respects human-edited and locked pages.
- `list_wiki_lint_issues(status="open")` and `resolve_wiki_lint_issue(issue_id, status="resolved")`: Inspect and resolve or dismiss wiki health findings.
- `get_wiki_status()`: Check wiki page counts, event cursor position, and open lint issue counts.
