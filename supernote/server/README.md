# Supernote Private Cloud Server

This package provides a self-hosted implementation of the Supernote Cloud server, enhanced with AI-powered insights, a modern Web UI, and robust background processing.

## Core Features

-   **Seamless Sync**: Implements the native Supernote sync protocol.
-   **AI Synthesis**: Automatically transcribes handwriting and identifies key insights using Google Gemini or Mistral AI.
-   **Knowledge Exploration**: Cross-notebook semantic search and web-based file browsing.
-   **Private & Local**: Store your notes and metadata on your own infrastructure.

## Getting Started

See the main [README.md](../../README.md) for a quick start guide.

### Prerequisites

-   A Supernote device (Nomad, A5 X, A6 X, etc.)
-   Python 3.13+ or Docker.
-   (Recommended) A **Gemini** or **Mistral AI** API key for OCR and Summarization.

### Configuration

The server is configured via `config/config.yaml` or environment variables.

For a comprehensive reference, see the [ServerConfig documentation](https://allenporter.github.io/supernote/supernote/server.html#ServerConfig).

#### AI Configuration

AI features require an API key from either Google Gemini (default) or Mistral AI. Set one of the following:

```bash
# Option A: Google Gemini (default)
export SUPERNOTE_GEMINI_API_KEY="your-gemini-api-key"

# Option B: Mistral AI (takes priority when set)
export SUPERNOTE_MISTRAL_API_KEY="your-mistral-api-key"
```

> **Note on provider switching**: Gemini embeddings are 3072-dimensional while Mistral embeddings are 1024-dimensional. Switching providers after notes have been indexed requires re-processing all files to regenerate embeddings.

Additional Gemini model settings:

| Env var | Default | Description |
|---|---|---|
| `SUPERNOTE_GEMINI_OCR_MODEL` | `gemini-3-flash-preview` | Vision model for OCR |
| `SUPERNOTE_GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Embedding model |
| `SUPERNOTE_GEMINI_CHAT_MODEL` | `gemini-2.0-flash` | Chat model for summaries |
| `SUPERNOTE_GEMINI_MAX_CONCURRENCY` | `5` | Max concurrent API calls (minimum 1) |

Additional Mistral model settings:

| Env var | Default | Description |
|---|---|---|
| `SUPERNOTE_MISTRAL_OCR_MODEL` | `mistral-ocr-latest` | Dedicated OCR model |
| `SUPERNOTE_MISTRAL_EMBEDDING_MODEL` | `mistral-embed` | Embedding model |
| `SUPERNOTE_MISTRAL_CHAT_MODEL` | `mistral-large-latest` | Chat model for summaries |
| `SUPERNOTE_MISTRAL_MAX_CONCURRENCY` | `5` | Max concurrent API calls (minimum 1) |

### Running the Server

Start the server using the unified `supernote` CLI:

```bash
# Start the server on port 8080
supernote serve
```

To override settings via environment:

```bash
export SUPERNOTE_PORT=8080
export SUPERNOTE_HOST=0.0.0.0
supernote serve
```

### Running with Docker

```bash
# Build the image
docker build -t supernote .

# Run the container
docker run -d \
  -p 8080:8080 \
  -v $(pwd)/storage:/storage \
  -e SUPERNOTE_GEMINI_API_KEY="your-key" \
  --name supernote-server \
  supernote serve
```

### Connecting Your Device

1. Review the [official Private Cloud setup guide](https://support.supernote.com/Whats-New/setting-up-your-own-supernote-private-cloud-beta).
2. Ensure your Supernote device and server are on the same Wi-Fi network.
3. On your Supernote device, go to **Settings** > **Sync** > **Supernote Cloud**.
4. Select **Private Cloud** and enter your server's IP and port (e.g., `192.168.1.100:8080`).
5. Attempt to login using the credentials created via `supernote admin user add`.
6. Configure folders to sync (e.g., `Note`, `Document`, `EXPORT`) in **Settings** > **Drive** > **Private Cloud**.

## Robustness & Maintenance

Supernote Knowledge Hub is built for long-term stability:

- **Database Migrations**: Uses Alembic for seamless schema updates.
- **Background Polling**: Automatically recovers stalled processing tasks.
- **Integrity Checks**: Periodically verifies file storage consistency.
- **Storage Quotas**: Manage user storage limits effectively.

## Debugging & Tracing

The server logs all incoming requests to `storage/system/server_trace.log`:

```bash
tail -f storage/system/server_trace.log
```

## Development

- **Entry Point**: `supernote/server/app.py`
- **Tests**: `tests/server/`
- **Ephemeral Mode**: Run `supernote serve --ephemeral` for a transient, pre-configured test instance.

For contribution guidelines, see [CONTRIBUTING.md](../docs/CONTRIBUTING.md).
