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

In the Web UI, click the **Settings** gear icon in the top-right bar, open **Access & API Keys** (`#/settings`), and create a named key under **API keys** (with an optional expiry of `30 days`, `90 days`, `1 year`, or `Never expires`). Copy the `sn_...` secret immediately—it is shown only once—and revoke keys from the same panel at any time.

Prefer the terminal? You can also mint, list, and revoke keys with the CLI:

```bash
# Log in once interactively
supernote cloud login you@example.com --url http://localhost:8080

# Mint a revocable API key (the secret is shown once)
supernote cloud keys create "claude-code" --expires-days 90

# List or revoke keys at any time
supernote cloud keys list
supernote cloud keys revoke <key-id>
```

### Managing OAuth 2.1 clients in the Web UI

When you connect an OAuth 2.1 client (such as Claude Desktop, Cursor, or ChatGPT), your browser opens the Web UI sign-in screen followed by an **Authorize Application** consent card showing the client's name, redirect target, and requested scopes so you can approve or deny access.

To audit or revoke access later, open **Settings → Access & API Keys** (`#/settings`) and scroll to **Connected clients**. Each authorized client shows its scopes, connection date, last-used timestamp, and expiry; clicking **Disconnect** immediately revokes both its access and refresh tokens.

### Claude Code

```bash
claude mcp add --transport http supernote http://localhost:8081/mcp \
  --header "Authorization: Bearer sn_your_api_key_here"
```

### Claude Desktop & Cursor (`mcp-remote` or native Streamable HTTP)

For clients that support Streamable HTTP (native remote MCP over HTTP) with OAuth 2.1, point the client at `http://<your-server>:8081/mcp`, or your HTTPS reverse-proxy URL. When running behind Caddy or Nginx, set `base_url` and `mcp_base_url` in `config/config.yaml`.

If you prefer a static API key in `claude_desktop_config.json`, use `mcp-remote`, which bridges Claude Desktop's local config to your HTTP MCP server using Node.js/`npx`:

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
| `get_page_image` | Return a normalized PNG image for a `.note` page or standalone image so vision models can inspect sketches and diagrams. | `file_id`, `page_index=0`, `max_dimension=1568` (`64`–`2048`) |

### Digests & AI Notebook Summaries

| Tool | Purpose | Key arguments |
| :--- | :--- | :--- |
| `list_digests` | List Digest entries (PDF/EPUB excerpts, lassoed note excerpts, typed comments, AI Notebook Summaries) with inline handwritten annotation OCR transcripts. | `file_id`, `category_id`, `limit=50`, `offset=0` |

### Files & folders

| Tool | Purpose | Key arguments |
| :--- | :--- | :--- |
| `list_files` | Browse files and folders across your Supernote cloud storage. | `path="/"`, `recursive=False` |
| `upload_document` | Upload a UTF-8 text or base64 binary document (up to 10 MiB) into a cloud folder and sync it to your tablet. | `directory_path`, `file_name`, `content`, `encoding="utf-8"`, `overwrite=False` |
| `create_folder` | Create a new folder path in your cloud storage (including missing parent directories). | `path` |
| `delete_item` | Move a file or folder to the recycle bin (soft delete); protected system folders cannot be deleted. | `file_id` |

### Tasks & schedule

| Tool | Purpose | Key arguments |
| :--- | :--- | :--- |
| `list_tasks` | List task groups and tasks, optionally filtered by group, completion state, or linked notebook. | `group_id`, `include_completed=False`, `file_id` |
| `create_task` | Create a Supernote task, optionally linked to a specific notebook page. | `title`, `detail`, `due_time`, `importance`, `group_id`, `linked_file_id`, `linked_page_number` |
| `update_task` | Update a task's fields, completion state, or linked notebook page. | `task_id`, `title`, `status`, `due_time`, `clear_link=False` |
| `delete_task` | Delete a task. | `task_id` |

### Domain event feed

| Tool | Purpose | Key arguments |
| :--- | :--- | :--- |
| `list_events` | Poll your account's incremental event feed for file, note, and task changes. | `event_types`, `file_id`, `limit=200` |

### LLM Wiki tools (when `wiki.enabled: true`)

When the opt-in [LLM Wiki](./llm_wiki.md) is enabled, eight additional tools are registered:

| Tool | Purpose | Key arguments |
| :--- | :--- | :--- |
| `get_wiki_index` | Fetch a compact index of active wiki pages. | `limit=100` |
| `list_wiki_pages` | Browse active wiki pages with optional kind filtering and pagination. | `page_kind`, `limit=50`, `offset=0` |
| `read_wiki_page` | Read a page's full Markdown body, aliases, backlinks, edit policy, and source citations. | `slug` |
| `search_wiki` | Search wiki titles, aliases, summaries, and bodies with linked pages and source snippets. | `query`, `top_k=10` |
| `upsert_wiki_page` | Create or update a wiki page while respecting human-edited and locked pages. | `slug`, `title`, `body_md` |
| `list_wiki_lint_issues` | List open or resolved wiki health findings. | `status="open"` |
| `resolve_wiki_lint_issue` | Mark a wiki health finding as resolved or dismissed. | `issue_id`, `status="resolved"` |
| `get_wiki_status` | Check wiki page counts, sync progress, and open lint issue counts. | *(none)* |

## Next steps

- Exposing your MCP server over HTTPS? See [Reverse proxy and TLS](./bootstrap_guide.md#reverse-proxy-and-tls) for Caddy and Nginx examples.
- For all MCP port, OAuth, and base URL settings, see the [Configuration Reference](../reference/configuration.md).
