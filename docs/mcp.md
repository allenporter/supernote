# AI Pipeline, Custom Prompts & MCP Server

The **Open Private Cloud for Supernote** server transforms binary `.note` files into searchable transcripts, vector embeddings, and structured chronological summaries, and exposes them to AI assistants (such as Claude, ChatGPT, Cursor, or local LLMs) via a built-in [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server.

---

## Background Processing Pipeline

When a `.note` file is uploaded or synchronized, `supernote.server.services.processor.ProcessorService` orchestrates an incremental, idempotent 5-stage pipeline tracked in SQLite (`SystemTaskDO`, `NoteMetadataDO`, `NotePageMetadataDO`, and `NotePageContentDO`):

```mermaid
flowchart TD
    Sync[".note File Synced"] --> S1["1. PageHashingModule<br/>Parse metadata & page MD5s"]
    S1 -->|Changed Pages| S2["2. PngConversionModule<br/>Rasterize page to PNG"]
    S2 --> S3["3. OcrModule<br/>Vision LLM transcript (skips blank pages)"]
    S3 --> S4["4. EmbeddingModule<br/>Vector embedding for search"]
    S4 --> S5["5. SummaryModule<br/>Notebook AI summary"]
```

### Stage Breakdown

| Stage | Module | Scope | Behavior & Invalidation Rules |
| :---: | :--- | :---: | :--- |
| **1** | `supernote.server.services.processor_modules.page_hashing.PageHashingModule` (`PAGE_HASHING`) | File | Parses the binary `.note` header/footer (`NoteMetadataDO`) and per-page metadata (`NotePageMetadataDO`: `page_style`, `has_ink`, `has_drawables`, `keywords_json`, `titles_json`, `links_json`). Computes an MD5 `content_hash` per page (`PAGEID`). Only pages whose hash changed have their downstream checkpoints invalidated; unchanged pages reuse cached ink/drawable state without re-parsing layer streams. |
| **2** | `supernote.server.services.processor_modules.png_conversion.PngConversionModule` (`PNG_CONVERSION`) | Page | Rasterizes modified pages into PNG blobs in `supernote-cache/`. Enabled when `web_enabled` + `web_notebook_preview` is `true`, or whenever `ai.ocr` is configured. |
| **3** | `supernote.server.services.processor_modules.ocr.OcrModule` (`OCR_EXTRACTION`) | Page | If `NotePageMetadataDO.has_drawables` is `False` (blank page), immediately writes `text_content = ""` without requiring a PNG or calling the LLM. Otherwise sends the page PNG and formatted prompt (`supernote.server.ai.prompts.format_ocr_prompt`) to `supernote.server.ai.models.ocr.OcrModel` and stores the Markdown transcript in `NotePageContentDO.text_content`. |
| **4** | `supernote.server.services.processor_modules.embedding.EmbeddingModule` (`EMBEDDING_GENERATION`) | Page | Skips blank pages (`content.is_blank`). Embeds non-blank `text_content` via `supernote.server.ai.models.embedding.EmbeddingModel` (`RETRIEVAL_DOCUMENT`). Tracks `model_id` as the task version—switching `ai.embedding.model` automatically re-embeds existing pages in the background. |
| **5** | `supernote.server.services.processor_modules.summary.SummaryModule` (`SUMMARY_GENERATION`) | File | Concatenates non-blank page transcripts in memory with `--- Page N ---` headers (including `Page Keywords:` when present) and invokes `supernote.server.ai.models.summary.SummaryModel` to produce date-segmented Markdown summaries (`SummaryResponse`) filed under the shared `"AI Summaries"` Digest category. |

> [!TIP]
> **Blank Page Skipping**: Pages with no foreground ink, textboxes, or vector graphics (`NotePageMetadataDO.has_drawables == False`) automatically short-circuit OCR, vector embedding, and summary calls—saving API tokens and latency on pre-created template notebooks.

### Managing Pipeline Tasks via CLI

Administrators can inspect, pause, resume, or force-reprocess pipeline stages at any time:

```bash
# View queue status and currently processing file IDs
supernote admin queue status

# Pause or resume background processing
supernote admin queue stop
supernote admin queue start

# Inspect recent tasks or filter by failed status
supernote admin tasks --status failed
supernote admin tasks --type ocr --file-id 42

# Force reprocessing of summaries (or all/ocr/png/embedding) across one or all files
supernote admin reprocess --type summary
supernote admin reprocess --type all --file-id 42
```

---

## Configuring Cloud, Local & On-Device AI Models

AI capabilities (`ocr`, `summary`, `embedding`) are configured independently in `config/config.yaml` via `supernote.server.config.AiConfig`. You can use cloud providers (`gemini`, hosted `openai`), local inference servers (`openai` provider pointed at Ollama, vLLM, llama.cpp, or LM Studio), macOS on-device Vision (`apple`), or mix them per capability.

> [!TIP]
> **Model Recommendation & Benchmarks**: We recommend `gemini-3.5-flash-lite` (or `gemini-3.6-flash`) for its strong multimodal handwriting recognition accuracy and low cost. For detailed CER/WER accuracy numbers, Bullet Journal structure fidelity, and latency comparisons across Gemini, Supernote On-Device (`MyScript iink`), and Apple Vision, see `supernote.guides.ocr_benchmarks` ([OCR Provider Benchmarks](../evals/ocr/RESULTS.md)).

### Mixing Cloud & Local Providers per Capability

```yaml
ai:
  providers:
    gemini:
      api_key: "AIzaSyYourGeminiKey"
    openai:
      base_url: "http://localhost:11434/v1"

  ocr:
    provider: gemini
    model: gemini-3.5-flash-lite  # or gemini-3.6-flash
    max_concurrency: 5

  summary:
    provider: openai
    model: gemma3:27b
    max_concurrency: 1

  embedding:
    provider: openai
    model: embeddinggemma
    max_concurrency: 2
```

### Named Provider Entries (`type: openai`)

By default, a provider entry's backend implementation matches its key name (`gemini`, `openai`, `apple`). To use multiple servers of the same kind (for example, `ollama` for chat/summarization and `llamacpp` for embeddings), give each entry a custom name and set `type: openai` (`supernote.server.config.ProviderConfig.type`):

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

### macOS On-Device Vision OCR (`apple` Provider)

On macOS (`pip install "supernote[server,apple]"`), Apple's on-device `Vision` framework (`vision-accurate`) is supported as an offline fallback for basic prose search without an API key or model server. Avoid `vision-fast`, which only detects machine-printed text:

```yaml
ai:
  ocr:
    provider: apple
    model: vision-accurate
    max_concurrency: 2
```

---

## Customizing AI Prompts, Page-Style Routing & Page Keywords

Prompts are managed by `supernote.server.utils.prompt_loader.PromptLoader` (`PROMPT_LOADER`). By default, the server loads built-in Bullet Journal / Rapid Logging prompts from `supernote/server/resources/prompts/`.

To override prompts with your own instructions, point `prompts_dir` (`SUPERNOTE_PROMPTS_DIR`) to a custom directory:

```yaml
# config/config.yaml
prompts_dir: /data/config/prompts
```

### Prompt Directory Layout

`PromptLoader` reads two top-level categories: `ocr` (`PromptId.OCR_TRANSCRIPTION`) and `summary` (`PromptId.SUMMARY_GENERATION`). Within each category, all `.md` files inside a subdirectory are sorted alphabetically and concatenated with `\n\n`:

```text
prompts/
├── ocr/
│   ├── common/               # Always prepended to EVERY OCR prompt
│   │   ├── context.md
│   │   └── legend.md
│   ├── default/              # Appended when no notebook-stem or page_style folder matches
│   │   ├── system.md
│   │   ├── rapid_logging.md
│   │   ├── handwriting.md
│   │   └── output_rules.md
│   ├── daily/                # Matches "Daily.note" OR pages with PAGESTYLE "user_Daily"
│   │   └── prompt.md
│   ├── 8mm_ruled_line/       # Matches pages with PAGESTYLE "style_h_8mm_ruled_line_a5x2"
│   │   └── prompt.md
│   └── meeting_notes/        # Matches "Meeting_Notes.note" OR PAGESTYLE "user_meeting_notes"
│       └── prompt.md
└── summary/
    ├── common/               # Always prepended to EVERY Summary prompt
    │   └── instruction.md
    ├── default/              # Appended when no notebook-specific folder matches
    │   └── prompt.md
    ├── daily/                # Appended when summarizing "Daily.note"
    │   └── prompt.md
    └── meeting_notes/        # Appended when summarizing "Meeting_Notes.note"
        └── prompt.md
```

### Prompt Routing Precedence: Filename Stem -> `page_style` -> `default`

When `OcrModule` formats a page prompt via `supernote.server.ai.prompts.format_ocr_prompt`, it resolves the custom prompt subdirectory using a 3-step fallback hierarchy based on `supernote.server.utils.note_content.PageMetadata`:

1. **Notebook Filename Stem (`file_name_basis`)**: Lowercase stem of the `.note` filename (`Path(file_name).stem.lower()`, e.g., `Daily.note` -> `"daily"`). If `ocr/<file_name_basis>/` exists, it is used.
2. **Stationery Template Style (`page_style_basis`)**: If no filename-specific prompt directory exists, `format_ocr_prompt` checks the page's normalized `.note` `PAGESTYLE` attribute (`supernote.server.utils.note_content.normalize_page_style_type`), which:
   - Lowercases the raw `PAGESTYLE` string (from `NotePageMetadataDO.page_style`),
   - Strips leading `user_`, `style_h_`, or `style_` prefixes, and
   - Strips trailing device-size suffixes (`_a5x2`, `_a5x`, `_a6x2`, `_a6x`, `_n5`, `_n6`).
   - Examples: `"user_Daily"` -> `"daily"`, `"style_h_8mm_ruled_line_a5x2"` -> `"8mm_ruled_line"`, `"style_cornell"` -> `"cornell"`.
   - If `ocr/<page_style_basis>/` exists, it is used for that page—allowing mixed-template notebooks to route individual pages to specialized prompts.
3. **Default Prompt (`default`)**: Falls back to `ocr/default/*.md`.

$$\text{Final OCR Prompt} = \text{Page Header} + \text{ocr/common/*.md} + \begin{cases} \text{ocr/<file\_name\_basis>/*.md} & \text{if exists} \\ \text{ocr/<page\_style\_basis>/*.md} & \text{else if exists} \\ \text{ocr/default/*.md} & \text{otherwise} \end{cases}$$

### Native `.note` Page Keywords Injection

When you tag a page with native keywords on your Supernote tablet, `PageHashingModule` extracts them into `NotePageMetadataDO.keywords_json` (`keyword_texts`). During OCR and transcript assembly, `supernote.server.utils.note_content.format_page_metadata` automatically injects a `Page Keywords:` line into the page header block:

```text
--- Page 1 ---
Notebook: Daily.note
Created: 2026-08-04 (Tuesday)
Page ID: P20260804090000
Page Keywords: Architecture, Q3-Planning
```

This grounds both the vision OCR model (improving domain terminology recognition) and the downstream `SummaryModule` synthesis.

> [!IMPORTANT]
> When customizing `summary/` prompts, keep instructions compatible with the structured JSON output schema (`supernote.server.ai.prompts.SummaryResponse`), which expects a `segments` array containing `date_range`, `summary` (Markdown string), `extracted_dates` (`YYYY-MM-DD` strings), and `page_refs` (1-indexed page numbers).

---

## Model Context Protocol (MCP) Server & Authentication

When `mcp_enabled: true` (default), Open Private Cloud runs a Streamable HTTP **MCP Resource Server** on `http://<your-server-ip>:8081/mcp` alongside an **OAuth 2.1 / IndieAuth Authorization Server** on port `8080` (`supernote.server.components.mcp.server` and `supernote.server.components.oauth.provider`).

### Dual-Port OAuth 2.1 + Streamable HTTP Topology

| Port | Role | Endpoints Exposed | Configuration |
| :---: | :--- | :--- | :--- |
| **`8080`** *(Main Server)* | **OAuth 2.1 Authorization Server (AS)** & Web UI | `/.well-known/oauth-authorization-server`<br>`/authorize`<br>`/login-bridge`<br>`/token`<br>`/revoke` | Public URL configured via `base_url` (`SUPERNOTE_BASE_URL`). |
| **`8081`** *(MCP Server)* | **MCP Resource Server (RS)** (Streamable HTTP) | `/.well-known/oauth-protected-resource`<br>`/mcp` | Port configured via `mcp_port` (`SUPERNOTE_MCP_PORT`). Public URL configured via `mcp_base_url` (`SUPERNOTE_MCP_BASE_URL`). |

### Two Authentication Modes for MCP Clients

`supernote.server.components.oauth.provider.SupernoteOAuthProvider` accepts two types of Bearer credentials on `http://<host>:8081/mcp`:

#### Mode 1: Interactive OAuth 2.1 with Dynamic IndieAuth Client IDs

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
    AS-->>Client: OAuth 2.1 metadata (/authorize, /token)
    Client->>Browser: Open /authorize?client_id=http://...&code_challenge=...
    Browser->>AS: Redirects through /login-bridge -> /#login?return_to=...
    Browser->>AS: User signs in & approves OAuth Consent Card; POST /login-bridge issues auth code
    AS-->>Client: Redirect to callback with ?code=...
    Client->>AS: POST /token (PKCE code_verifier)
    AS-->>Client: Bearer access_token (1h TTL) + refresh_token (30d TTL)
    Client->>RS: POST /mcp (Authorization: Bearer <access_token>)
    RS-->>Client: Streamable HTTP MCP Tool Execution
```

- **Zero Client Pre-Registration**: Any valid `http://` or `https://` URL passed as `client_id` is accepted dynamically, and any `redirect_uri` sharing the same scheme, host, and path prefix is permitted.
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

### Custom OAuth 2.1 Agents (IndieAuth)

When building a custom web agent, use your application's URL as the `client_id`:

```python
params = {
    "response_type": "code",
    "client_id": "https://my-agent-app.com",
    "redirect_uri": "https://my-agent-app.com/callback",
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

### Schedule Task CRUD Tools (`supernote.server.components.schedule.mcp`)

The `schedule` component registers four To-Do management tools via the `mcp` platform (`McpRegistrar`), supporting notebook page deep-links (`ScheduleTaskLinkDTO`), real-time `TASK-SYN` Socket.IO device push, and Domain Event Log attribution:

- **`list_tasks(group_id=None, include_completed=False, file_id=None)`**: Lists task groups and tasks (including decoded `link` metadata and timestamps), optionally filtered by group, completion status, or linked notebook `file_id`.
- **`create_task(title, detail=None, status=None, importance=None, due_time=None, group_id=None, linked_file_id=None, linked_file_path=None, linked_page_id=None, linked_page_number=None, cause_seq=None, reason=None)`**: Creates a task and optionally encodes a notebook/page deep-link.
- **`update_task(task_id, ..., clear_link=False, cause_seq=None, reason=None)`**: Partially updates task fields, manages `completed_time` on status transitions, merges or clears (`clear_link=True`) notebook deep-links, and normalizes `due_time=0` to `None`.
- **`delete_task(task_id, cause_seq=None, reason=None)`**: Deletes a user-scoped task and emits a `schedule.task_deleted` tombstone event.

#### Causal Event Provenance (`cause_seq` & `reason`)

Mutating MCP tools accept optional `cause_seq` (the triggering domain event sequence ID, up to 64 chars) and `reason` (human-readable explanation, up to 500 chars) arguments. Internally, handlers wrap service calls with `supernote.server.events.bind_event_provenance(cause_seq=..., reason=...)`, which merges those fields into the `payload` of any `DomainEvent` recorded in `f_user_event` alongside the caller's canonical `actor` (`oauth:<client_id>`, `api_key:<id>`, or `user:web`). This lets automated clients and activity views trace *why* a mutation happened and which prior event triggered it.
