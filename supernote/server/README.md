# Supernote Private Cloud Server

This package provides a self-hosted implementation of the Supernote Cloud server, enhanced with AI-powered insights and robust background processing.

## Getting Started

### Prerequisites

- A Supernote device (A5 X, A6 X, Nomad, etc.)
- A computer running this server (accessible on your local network)
- (Optional) Gemini API Key for OCR and Summarization

### Configuration

The server is configured via `config/config.yaml` or environment variables.

For a comprehensive reference, see the [ServerConfig documentation](https://allenporter.github.io/supernote-lite/supernote/server.html#ServerConfig).

#### AI Configuration
To enable AI features, set the Gemini API key:
```bash
export SUPERNOTE_GEMINI_API_KEY="your-api-key"
```

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

Supernote-Lite is built for long-term stability:

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
