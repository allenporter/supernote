# MCP Server & AI Assistants

Open Private Cloud includes an optional [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server (`mcp_enabled: true` by default) that lets AI assistants like Claude Desktop, Claude Code, Cursor, or custom scripts search your notebooks, read transcripts, inspect hand-drawn diagrams as PNG images, manage tasks, and update your LLM Wiki.

Looking for OCR setup, custom prompts, or AI provider benchmarks instead? See [Handwriting OCR & Multimodal Workflows](./ocr_and_multimodal.md), [Hybrid Search & Retrieval](./search.md), [Choosing an AI Provider](./ai_providers.md), or the [Async Note Processing Pipeline](../architecture/note_processing_design.md).

## What an assistant can do

A typical multimodal workflow with Claude or Cursor looks like this:

1. Search across your notebooks with `search_notebook_chunks` (or browse recent files with `list_notebooks`).
2. Read full page text with `get_notebook_transcript`.
3. Call `get_page_image(file_id, page_index)` when you want the assistant to actually look at a hand-drawn diagram, floor plan, or whiteboard photo.
4. Create or update Supernote To-Do items (`create_task`, `update_task`) or read and edit your compiled [LLM Wiki](./llm_wiki.md) (`search_wiki`, `read_wiki_page`, `upsert_wiki_page`).

---

## Server Topology & Authentication

When `mcp_enabled: true` (default), Open Private Cloud runs a Streamable HTTP **MCP Resource Server** on `http://<your-server-ip>:8081/mcp` alongside an **OAuth 2.1 Authorization Server** on port `8080`.

### Dual-Port OAuth 2.1 + Streamable HTTP Topology

| Port | Role | Endpoints Exposed | Configuration |
| :---: | :--- | :--- | :--- |
| **`8080`** *(Main Server)* | **OAuth 2.1 Authorization Server (AS)** & Web UI | `/.well-known/oauth-authorization-server`<br>`/authorize`<br>`/login-bridge`<br>`/token`<br>`/revoke` | Public URL configured via `base_url` (`SUPERNOTE_BASE_URL`). |
| **`8081`** *(MCP Server)* | **MCP Resource Server (RS)** (Streamable HTTP) | `/.well-known/oauth-protected-resource`<br>`/mcp` | Port configured via `mcp_port` (`SUPERNOTE_MCP_PORT`). Public URL configured via `mcp_base_url` (`SUPERNOTE_MCP_BASE_URL`). |

### Two Authentication Modes for MCP Clients

`supernote.server.components.oauth.provider.SupernoteOAuthProvider` accepts two types of Bearer credentials on `http://<host>:8081/mcp`:

#### Mode 1: Interactive OAuth 2.1 with Client ID Metadata Documents

```mermaid
sequenceDiagram
    participant Client as MCP Client (Claude / Cursor)
    participant RS as MCP Resource Server (:8081/mcp)
    participant AS as Authorization Server (:8080)
    participant Browser as User Browser (Web UI)

    Client->>RS: POST /mcp (unauthenticated)
    RS-->>Client: 401 Unauthorized (RFC 9728 Protected Resource Metadata)
    Client->>RS: GET /.well-known/oauth-protected-resource
    RS-->>Client: Returns authorization_servers: ["http://localhost:8080"]
    Client->>AS: GET /.well-known/oauth-authorization-server
    AS-->>Client: OAuth 2.1 metadata (client_id_metadata_document_supported: true)
    Client->>Browser: Open /authorize?client_id=https://client.example/client.json&code_challenge=...
    AS->>Client: GET client_id URL (Client ID Metadata Document)
    Browser->>AS: Redirects through /login-bridge -> /#login?return_to=...
    Browser->>AS: User signs in & approves OAuth Consent Card; POST /login-bridge issues auth code
    AS-->>Client: Redirect to callback with ?code=...
    Client->>AS: POST /token (PKCE code_verifier)
    AS-->>Client: Bearer access_token (1h TTL) + refresh_token (30d TTL)
    Client->>RS: POST /mcp (Authorization: Bearer <access_token>)
    RS-->>Client: Streamable HTTP MCP Tool Execution
```

- **Zero Client Pre-Registration**: Clients identify themselves with [Client ID Metadata Documents](https://datatracker.ietf.org/doc/draft-ietf-oauth-client-id-metadata-document/), as the MCP authorization spec recommends. The `client_id` is an `https://` URL with a path, and the server fetches the JSON document it serves. The document must repeat that exact `client_id` and include `client_name` and `redirect_uris`. It must not carry a `client_secret`, because clients are public and authenticate with PKCE (`token_endpoint_auth_method: none`). There is no `/register` endpoint.
- **IndieAuth-style Clients**: A `client_id` that is not an `https://` URL with a path, points at a private or LAN address, or does not serve a JSON document (common for self-hosted and LAN clients) is accepted as before: any `redirect_uri` sharing its scheme, host, and path prefix is permitted. Private addresses are never fetched.
- **Exact Redirect URIs**: For a client with a document, a `redirect_uri` must equal one listed in it. Listed URIs must be `https://`, `http://` on `localhost`, `127.0.0.1` or `[::1]`, or a native app's own scheme (`com.example.app:/callback`). The port of a loopback redirect may vary (RFC 8252). Script, data and file schemes are refused.
- **Fetching**: Documents are fetched over HTTPS from public addresses only. Redirects are not followed and a fetch times out after 5 seconds. A 200 JSON response (`application/json` or `+json`) of at most 5 KB is a document; any other answer except 429 or 5xx means the client has none. Valid documents are cached for their `Cache-Control: max-age`, bounded to 5 minutes to 1 day (1 hour without one). `no-store` and `no-cache` documents are fetched on every use. Failures are never cached. If a document is invalid, the server shows an error instead of redirecting to the client. If it is unreachable, the server answers 503.
- **Token Lifetimes**: OAuth access tokens expire after **1 hour** (`3600` seconds) and refresh tokens remain valid for **30 days**.
- **Connected Clients**: Each approved authorization is recorded as a grant. `GET /api/extended/oauth/grants` lists them with their scopes and last use, and `DELETE /api/extended/oauth/grants/{grantId}` disconnects a client, ending its access and refresh tokens at once.

#### Mode 2: Static Bearer API Keys (`sn_...`)

For headless agents, local CLI tools, or MCP clients that do not run an interactive browser OAuth flow, generate a revocable static API key (`sn_...`, stored as a SHA-256 hash in `ApiKeyDO` / `f_api_key`):

```bash
# Authenticate once interactively
supernote cloud login you@example.com --url http://localhost:8080

# Create a static API key
supernote cloud keys create "claude-code"
# Output: Created API key 'claude-code' (id=1): sn_...

# List or revoke keys at any time
supernote cloud keys list
supernote cloud keys revoke 1
```

Pass `Authorization: Bearer sn_...` directly to `http://localhost:8081/mcp` (or any REST endpoint).

---

## Connecting MCP Clients

### Claude Desktop / Cursor via OAuth (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "supernote": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://localhost:8081/mcp"
      ]
    }
  }
}
```

### Headless MCP Clients via Static Bearer API Key (`sn_...`)

For MCP clients that support static `headers` on Streamable HTTP connections:

```json
{
  "mcpServers": {
    "supernote": {
      "url": "http://localhost:8081/mcp",
      "headers": {
        "Authorization": "Bearer sn_your_api_key_here"
      }
    }
  }
}
```

### Custom OAuth 2.1 Agents

When building a custom agent, publish a Client ID Metadata Document at a stable HTTPS URL and use that URL as the `client_id`:

```json
{
  "client_id": "https://my-agent-app.example/oauth/client.json",
  "client_name": "My Agent",
  "redirect_uris": ["https://my-agent-app.example/callback"],
  "grant_types": ["authorization_code", "refresh_token"],
  "response_types": ["code"],
  "token_endpoint_auth_method": "none"
}
```

Without `grant_types`, a client gets both `authorization_code` and `refresh_token`. Then start the flow:

```python
params = {
    "response_type": "code",
    "client_id": "https://my-agent-app.example/oauth/client.json",
    "redirect_uri": "https://my-agent-app.example/callback",
    "scope": "supernote:all",
    "state": "xyz",
}
```

---

## Exposed MCP Tools Reference

Defined in `supernote.server.components.mcp.server` and validated by DTOs/VOs in `supernote.server.components.mcp.models`. All tools scope queries strictly to the authenticated user's notebooks.

### `list_notebooks`

Lists active `.note` notebooks ordered by most recently updated (`update_time` descending).

- **Arguments (`supernote.server.components.mcp.models.ListNotebooksRequestDTO`)**:
  | Parameter | Type | Default | Description |
  | :--- | :--- | :--- | :--- |
  | `limit` | `int` | `20` | Maximum number of notebooks to return. |
  | `name_filter` | `str \| None` | `None` | Optional case-insensitive substring filter on the notebook filename. |

- **Response Payload (`supernote.server.components.mcp.models.ListNotebooksResponseVO`)**:
  ```json
  {
    "success": true,
    "errorCode": null,
    "errorMsg": null,
    "notebooks": [
      {
        "fileId": "42",
        "fileName": "Daily.note",
        "createTime": 1754265600000,
        "updateTime": 1754352000000
      }
    ]
  }
  ```

### `search_notebook_chunks`

Performs semantic vector similarity search across all embedded notebook pages (`NotePageContentDO`), with optional filename and ISO 8601 date filtering.

- **Arguments (`supernote.server.components.mcp.models.SearchRequestDTO`)**:
  | Parameter | Type | Default | Description |
  | :--- | :--- | :--- | :--- |
  | `query` | `str` | *(required)* | Natural-language semantic search query (embedded with `RETRIEVAL_QUERY`). |
  | `top_n` | `int` | `5` | Maximum number of top-scoring page chunks to return. |
  | `name_filter` | `str \| None` | `None` | Optional substring filter for notebook filenames (e.g. `"Journal"`). |
  | `date_after` | `str \| None` | `None` | Include only notes/pages on or after this ISO 8601 date (`YYYY-MM-DD`). |
  | `date_before` | `str \| None` | `None` | Include only notes/pages on or before this ISO 8601 date (`YYYY-MM-DD`). |

- **Response Payload (`supernote.server.components.mcp.models.SearchResponseVO`)**:
  ```json
  {
    "success": true,
    "errorCode": null,
    "errorMsg": null,
    "results": [
      {
        "fileId": "42",
        "fileName": "Daily.note",
        "pageIndex": 3,
        "pageId": "P20260804120000",
        "score": 0.8742,
        "textPreview": "--- Page 4 ---\n• Finalize Q3 architecture proposal\nX Review VFS integrity service",
        "date": "2026-08-04"
      }
    ]
  }
  ```

### `get_notebook_transcript`

Retrieves the full OCR transcript for a notebook or slices a specific 0-based page range (`[start_index, end_index]` inclusive).

- **Arguments (`supernote.server.components.mcp.models.TranscriptRequestDTO`)**:
  | Parameter | Type | Default | Description |
  | :--- | :--- | :--- | :--- |
  | `file_id` | `str` | *(required)* | Numeric notebook ID string (as returned by `list_notebooks` or `search_notebook_chunks`). |
  | `start_index` | `int \| None` | `None` | 0-based starting page index (inclusive). If omitted, starts at page `0`. |
  | `end_index` | `int \| None` | `None` | 0-based ending page index (inclusive). If omitted, includes through the last page. |

- **Response Payload (`supernote.server.components.mcp.models.TranscriptResponseVO`)**:
  ```json
  {
    "success": true,
    "errorCode": null,
    "errorMsg": null,
    "transcript": "--- Page 1 ---\nNotebook: Daily.note\nCreated: 2026-08-04\nPage ID: P20260804090000\nPage Keywords: Architecture\n\n• Ship MCP documentation\nX Fix webhook signature verification"
  }
  ```

### `get_page_image` (`supernote.server.components.processor.mcp`)

Retrieves a normalized PNG image (`ImageContent`) alongside a metadata summary for a single `.note` page or standalone raster image file—allowing vision-capable assistants to inspect hand-drawn diagrams, sketches, or photos directly.

- **Arguments**:
  | Parameter | Type | Default | Description |
  | :--- | :--- | :--- | :--- |
  | `file_id` | `str` | *(required)* | Numeric ID string of the `.note` notebook or standalone image file. |
  | `page_index` | `int` | `0` | 0-based page index (must be `0` for standalone images). |
  | `max_dimension` | `int` | `1568` | Maximum longest-edge pixel dimension (`64`–`2048`). |

### Schedule Task CRUD Tools (`supernote.server.components.schedule.mcp`)

The `schedule` component registers four To-Do management tools via the `mcp` platform (`McpRegistrar`), supporting notebook page deep-links (`ScheduleTaskLinkDTO`), real-time `TASK-SYN` Socket.IO device push, and Domain Event Log attribution:

- **`list_tasks(group_id=None, include_completed=False, file_id=None)`**: Lists task groups and tasks (including decoded `link` metadata and timestamps), optionally filtered by group, completion status, or linked notebook `file_id`.
- **`create_task(title, detail=None, status=None, importance=None, due_time=None, group_id=None, linked_file_id=None, linked_file_path=None, linked_page_id=None, linked_page_number=None, cause_seq=None, reason=None)`**: Creates a task and optionally encodes a notebook/page deep-link.
- **`update_task(task_id, ..., clear_link=False, cause_seq=None, reason=None)`**: Partially updates task fields, manages `completed_time` on status transitions, merges or clears (`clear_link=True`) notebook deep-links, and normalizes `due_time=0` to `None`.
- **`delete_task(task_id, cause_seq=None, reason=None)`**: Deletes a user-scoped task and emits a `schedule.task_deleted` tombstone event.

### LLM Wiki Tools (`supernote.server.components.wiki.mcp`)

When `wiki.enabled: true` (`SUPERNOTE_WIKI_ENABLED=true`), the `wiki` component registers eight tools for navigating, searching, authoring, and maintaining the compiled Markdown knowledge graph:

- **`get_wiki_index(limit=100)`**: Returns a compact index of active wiki pages (`slug`, `title`, `page_kind`, `summary`) without full Markdown bodies for low-token orientation.
- **`list_wiki_pages(page_kind=None, limit=50, offset=0)`**: Paginates active wiki pages, optionally filtered by `page_kind` (`project`, `entity`, `topic`, `source_digest`, `index`, or `log`).
- **`read_wiki_page(slug)`**: Returns the full Markdown body, `version`, `edit_policy`, aliases, backlinks, and provenance `source_refs` for a single page.
- **`search_wiki(query, top_k=10)`**: Searches wiki page titles, aliases, summaries, and bodies, returning ranked hits with 1-hop links and source citations.
- **`upsert_wiki_page(slug, title, body_md, page_kind="topic", summary="", aliases=None, source_refs=None, expected_version=None, change_summary="")`**: Creates or updates a wiki page with optimistic concurrency (`expected_version`). Respects `edit_policy`: pages edited by a human (`protected_prose`) or `locked` reject agent writes with `403`.
- **`list_wiki_lint_issues(status="open")`**: Lists wiki health issues (`broken_link`, `orphan_page`, `stale_source`, `contradiction`, `duplicate_entity`, `alias_merge_proposal`), filtered by `open`, `resolved`, `dismissed`, or `all`.
- **`resolve_wiki_lint_issue(issue_id, status="resolved")`**: Marks a lint issue as `resolved` or `dismissed`.
- **`get_wiki_status()`**: Returns per-user wiki page counts, event cursor position, and open lint issue summary.

#### Causal Event Provenance (`cause_seq` & `reason`)

Mutating MCP tools accept optional `cause_seq` (the triggering domain event sequence ID, up to 64 chars) and `reason` (human-readable explanation, up to 500 chars) arguments. Internally, handlers wrap service calls with `supernote.server.events.bind_event_provenance(cause_seq=..., reason=...)`, which merges those fields into the `payload` of any `DomainEvent` recorded in `f_user_event` alongside the caller's canonical `actor` (`oauth:<client_id>`, `api_key:<id>`, or `user:web`). This lets automated clients and activity views trace *why* a mutation happened and which prior event triggered it.
