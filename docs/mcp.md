# AI & Agent Integration (MCP)

The **Open Private Cloud** server includes a built-in [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server. This allows AI agents (like Claude, ChatGPT, or local LLMs) to securely interact with your handwritten notes, perform semantic searches, and retrieve synthesized insights.

## Why use MCP with Supernote?

Handwritten notes are often "dead data"—captured once and rarely revisited. By exposing your notes via MCP, you can:
- **Chat with your notes**: Ask questions like "What was the feedback I wrote during the client meeting last Tuesday?"
- **Synthesize across notebooks**: Ask an agent to "Find all references to 'Project Phoenix' across all my 2024 journals and summarize the timeline."
- **Automate Workflows**: Let an agent extract action items from your handwriting and add them to your task manager.

## Connection & Setup

The Open Private Cloud MCP server is available at:
`http://<your-server-ip>:8081/mcp` (using Streamable HTTP).

> [!NOTE]
> The MCP service runs on port `8081` by default, while the main Open Private Cloud web interface and OAuth endpoints run on `8080`.

### Secure Authentication (IndieAuth/OAuth 2.1)

Open Private Cloud implements modern **Dynamic OAuth 2.1** (IndieAuth style).

- **Client ID**: Your Client ID should be a URL identifying the application or agent (e.g., `https://<your home assistant url>`).
- **Dynamic Registration**: You don't need to pre-register clients. The server will dynamically recognize and authorize clients based on their URL.
- **Login**: When an agent requests access, you will be redirected to the Open Private Cloud login page to authorize the session.

## Configuration for Popular Agents

### 1. Claude Desktop (Claude.ai)

To connect Claude to your Supernote notes, add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "supernote": {
      "command": "mcp-proxy",
      "args": ["http://localhost:8081/mcp"]
    }
  }
}
```

### 2. Custom Agents (IndieAuth)

When building a custom agent, use your application's URL as the `client_id`. Open Private Cloud will treat this as a trusted IndieAuth client:

```python
# Example OAuth request
params = {
    "response_type": "code",
    "client_id": "https://my-agent-app.com",
    "redirect_uri": "https://my-agent-app.com/callback",
    "scope": "supernote:all",
    "state": "xyz",
}
```

## Available Tools

The MCP server exposes specialized "Tools" that LLMs can call to explore your knowledge:

- `list_notebooks`: List active notebooks ordered by most recently updated (supports optional filename substring filtering and limit).
- `search_notebook_chunks`: Semantic search for content chunks across all notebooks (supports filtering by name and date).
- `get_notebook_transcript`: Retrieve the full AI-generated transcript or specific page ranges for a notebook.

---

> [!TIP]
> **Privacy First**: Your notes never leave your server except for the specific data requested by the AI agent during a session. All vector embeddings and indices stay on your local storage.
