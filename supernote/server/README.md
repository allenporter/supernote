# Supernote Private Cloud Server

This package provides a self-hosted implementation of the Supernote Cloud server, enhanced with AI-powered insights, a modern Web UI, and robust background processing.

## Core Features

-   **Seamless Sync**: Implements the native Supernote sync protocol.
-   **AI Synthesis**: Automatically transcribes handwriting and identifies key insights using Google Gemini.
-   **Knowledge Exploration**: Cross-notebook semantic search and web-based file browsing.
-   **Private & Local**: Store your notes and metadata on your own infrastructure.

## Getting Started

See the main [README.md](../../README.md) for a quick start guide.

### Prerequisites

-   A Supernote device (Nomad, A5 X, A6 X, etc.)
-   Python 3.13+ or Docker.
-   (Recommended) **Gemini API Key** for OCR and Summarization.

### Configuration

The server is configured via `config/config.yaml` or environment variables.

For a comprehensive reference, see the [ServerConfig documentation](https://allenporter.github.io/supernote/supernote/server.html#ServerConfig).

#### AI Configuration
Configure AI providers and per-capability models (`ocr`, `summary`, `embedding`) in `config/config.yaml` (omitting any capability you want disabled):
```yaml
ai:
  providers:
    gemini:
      api_key: "your-api-key"
  ocr:
    provider: gemini
    model: gemini-3.6-flash
    max_concurrency: 5
  summary:
    provider: gemini
    model: gemini-3.6-flash
    max_concurrency: 5
  embedding:
    provider: gemini
    model: gemini-embedding-001
    max_concurrency: 5
```

To run the models locally instead, use the `openai` provider with any server that implements the OpenAI API (e.g. Ollama, llama.cpp, vLLM, LM Studio). OCR needs a vision-capable chat model. Providers can be mixed per capability.
```yaml
ai:
  providers:
    openai:
      base_url: "http://localhost:11434/v1"  # Ollama; omit for api.openai.com
      # api_key: "sk-..."                    # required for hosted OpenAI
  ocr:
    provider: openai
    model: gemma3:27b
    max_concurrency: 1
  summary:
    provider: openai
    model: gemma3:27b
    max_concurrency: 1
  embedding:
    provider: openai
    model: embeddinggemma
    max_concurrency: 1
```
Embeddings from different models are not comparable, so after changing the embedding model run `supernote admin reprocess --type embedding`.

#### Outbound Webhooks
To send non-blocking HTTP `POST` notifications on server events (e.g., to Home Assistant, n8n, or Zapier), configure `webhooks` in `config/config.yaml` (or enable via `SUPERNOTE_WEBHOOKS_ENABLED=true`):
```yaml
webhooks:
  enabled: true
  endpoints:
    - url: "https://n8n.homelab.local/webhook/supernote"
      user: "user@example.com"
      secret: "CHANGE_ME_TO_A_SECURE_RANDOM_STRING"
      events:
        - "note.sync_completed"
```
Each delivery includes `X-Supernote-Event` and (when `secret` is set) `X-Supernote-Signature: sha256=<hex>` headers with a JSON payload (see [`supernote.models.webhook`](https://allenporter.github.io/supernote/supernote/models/webhook.html) and [`supernote.server.services.webhook`](https://allenporter.github.io/supernote/supernote/server/services/webhook.html)).

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

- **Database Migrations**: Uses Alembic for seamless schema and data updates (see [Alembic Migration History & Conventions](../alembic/README.md)).
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
