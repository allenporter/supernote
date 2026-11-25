# Self-Hosting & Quickstart Guide

This guide walks you through running Open Private Cloud on your own machine or home server, creating your admin account, pairing a Supernote tablet, setting up a reverse proxy, and backing up your data.

Open Private Cloud is an unofficial, community-developed Python server that speaks the Supernote Private Cloud protocol. It works with the Nomad (A6 X2), Manta (A5 X2), A5 X, and A6 X. Everything beyond basic sync is optional, and you do not need any AI provider to run it.

---

## Choose a deployment mode

You can run the server as a minimal sync target or keep the Web UI and MCP server enabled:

| Mode | Idle RAM | Peak RAM | What runs |
| :--- | :---: | :---: | :--- |
| Bare sync server | ~133 MB | ~135 MB | Native tablet sync (`Note`, `Document`, `EXPORT`, `INBOX`, `SCREENSHOT`), task sync, SQLite metadata, and local file storage. Disables the Web UI, page PNG rendering, and MCP. |
| Standard server (default) | ~160 MB | ~310 MB | Everything in bare sync, plus the Web UI, background `.note` page previews, the MCP server on port `8081`, and any AI features you opt into. |

To run in bare sync mode on a Raspberry Pi or low-memory VPS, disable the Web UI and MCP server in `config/config.yaml`:

```yaml
web_enabled: false
mcp_enabled: false
```

Or pass environment variables instead:

```bash
SUPERNOTE_WEB_ENABLED=false SUPERNOTE_MCP_ENABLED=false supernote serve
```

> [!TIP]
> If you want the Web UI for browsing files and tasks without background page rendering, leave `web_enabled: true` and set `web_notebook_preview: false` (`SUPERNOTE_WEB_NOTEBOOK_PREVIEW=false`). Note that configuring an OCR model automatically enables page PNG rendering.

---

## Install and start the server

### Option A: Python (`pip` or `uv`)

Requires Python 3.13 or newer.

```bash
# Install the server and the cloud/admin CLI tools
pip install "supernote[all]"

# Or install only the server runtime
pip install "supernote[server]"
```

Start the server:

```bash
# Uses ./config/config.yaml and ./storage by default
supernote serve

# Or point to a custom config directory
supernote serve --config-dir /etc/supernote
```

To try the server locally without keeping any data on disk, run `supernote serve --ephemeral`. It creates a temporary directory and pre-seeds a `debug@example.com` account with password `password`.

### Option B: Docker and Docker Compose

Pre-built container images are published to GitHub Container Registry as `ghcr.io/allenporter/supernote:latest`. The container runs as UID/GID `1000:1000`, stores all persistent data under `/data`, and reads `/data/config/config.yaml` if present.

#### `docker run` (zero-AI default)

```bash
docker run -d \
  --name supernote \
  --restart unless-stopped \
  -p 8080:8080 \
  -p 8081:8081 \
  -v "$(pwd)/storage:/data" \
  ghcr.io/allenporter/supernote:latest
```

#### `docker-compose.yml`

```yaml
services:
  supernote:
    image: ghcr.io/allenporter/supernote:latest
    container_name: supernote
    restart: unless-stopped
    ports:
      - "8080:8080" # Main HTTP API, Web UI, Socket.IO, OAuth 2.1
      - "8081:8081" # MCP server (/mcp)
    volumes:
      - ./storage:/data
    environment:
      SUPERNOTE_STORAGE_DIR: /data
      SUPERNOTE_CONFIG_DIR: /data/config
      SUPERNOTE_PROXY_MODE: relaxed
      # Optional: default per-user storage quota in bytes (0 = bounded by disk free space)
      # SUPERNOTE_DEFAULT_USER_QUOTA: "10737418240"
      # Optional: enable Gemini OCR, summaries, and hybrid search (or configure Ollama in config.yaml)
      # SUPERNOTE_GEMINI_API_KEY: "AIzaSy..."
```

> [!IMPORTANT]
> Make sure the host directory mounted to `/data` is writable by UID/GID `1000:1000` (for example, `chown -R 1000:1000 ./storage`).

If you want to add handwriting OCR, summaries, or semantic search later, see [Choosing an AI Provider](./ai_providers.md) for Google Gemini and 100% local Ollama/vLLM setups.

---

## Create your admin account

Open Private Cloud starts with an admin-first bootstrap flow. When the database is empty, registration is open for one account. The first user you register becomes the administrator, gets the default Supernote folders (`NOTE`, `DOCUMENT`, `EXPORT`, `INBOX`, `SCREENSHOT`), and automatically locks public registration for everyone else.

### 1. Register the first admin

```bash
supernote admin --url http://localhost:8080 user add you@example.com --name "Admin"
```

You will be prompted for a password (or pass `--password`). You can also register the first account from the Web UI sign-up screen at `http://localhost:8080`.

### 2. Sign in with the CLI

```bash
supernote cloud login you@example.com --url http://localhost:8080
```

This caches your session in `~/.cache/supernote.pkl` so later `supernote cloud` and `supernote admin` commands do not need `--url` or your password again.

### 3. Issue API keys for scripts and MCP

For automation, `.ics` feeds, and MCP clients, create a revocable static API key (`sn_...`) instead of reusing your login password:

```bash
# Create a key (printed once; save it somewhere safe)
supernote cloud keys create "laptop-automation"

# List active keys
supernote cloud keys list

# Revoke a key by ID
supernote cloud keys revoke 1
```

Pass the key with `--api-key`, `SUPERNOTE_API_KEY`, or an `Authorization: Bearer sn_...` header:

```bash
export SUPERNOTE_API_KEY="sn_..."
supernote cloud ls --url http://localhost:8080
```

Static API keys cannot mint new keys or change account passwords, so a leaked key stays scoped to normal API and MCP access.

### 4. Manage additional users and quotas

Once public registration is locked, add household or team members from the admin CLI:

```bash
# Add another user
supernote admin user add teammate@example.com --name "Teammate"

# Set a per-user storage quota (10 GiB in bytes, or 0 for uncapped)
supernote admin user set-quota teammate@example.com 10737418240

# List accounts and quotas
supernote admin user list

# Reset a user's password (also revokes their active sessions)
supernote admin user reset-password teammate@example.com

# Check background processing queue status
supernote admin queue status
```

Per-user quotas override the server-wide `default_user_quota` setting. When a user's quota is `0`, uploads are bounded by available free space on the storage volume.

---

## Pair your Supernote tablet

1. Make sure your tablet can reach the server over your local network, a VPN such as Tailscale or WireGuard, or an HTTPS reverse proxy.
2. On the tablet, swipe down from the top bar and open **Settings → Sync → Supernote Cloud**, then choose **Private Cloud**.
3. Enter your server address (for example, `http://192.168.1.50:8080` or `https://notes.example.com`) and sign in with the admin account you created above.
4. Under **Settings → Sync**, toggle the folders you want to sync (`Note`, `Document`, `EXPORT`, `INBOX`, `SCREENSHOT`).
5. Tap the **Sync** icon in the top pull-down bar.

Connected tablets keep a live Socket.IO connection to the server so changes made in the Web UI or on another device trigger sync automatically. While a multi-file sync session is running, background `.note` processing waits until the tablet finishes uploading so sync stays fast.

---

## Reverse proxy and TLS

When exposing Open Private Cloud behind Caddy, Nginx, or Traefik, set `base_url`, `proxy_mode` (`relaxed` or `strict`), and `mcp_base_url` (if you expose port `8081`). See the [Configuration Reference](../reference/configuration.md) for all proxy settings and defaults.

Three things to configure on your proxy:

1. Allow uploads up to `1 GB` so large `.note` files and PDFs do not fail with `413 Payload Too Large`.
2. Forward HTTP/1.1 `Upgrade` and `Connection` headers on `/socket.io/` for real-time sync notifications.
3. If you proxy port `8081` for remote MCP clients, disable response buffering on `/mcp` so streamed responses flush immediately.

### Caddy (`Caddyfile`)

```caddyfile
notes.example.com {
    request_body {
        max_size 1GB
    }
    reverse_proxy supernote:8080
}

mcp.notes.example.com {
    reverse_proxy supernote:8081 {
        flush_interval -1
    }
}
```

### Nginx (`nginx.conf`)

```nginx
server {
    listen 443 ssl http2;
    server_name notes.example.com;

    client_max_body_size 1G;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
    }

    location /socket.io/ {
        proxy_pass http://127.0.0.1:8080/socket.io/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400s;
    }
}
```

---

## Storage layout and backups

All persistent state lives inside `storage_dir` (`./storage` locally, `/data` in Docker):

```text
storage/
├── system/
│   ├── supernote.db          # SQLite database (users, files, tasks, OCR text, embeddings, summaries, events)
│   └── trace.log             # Optional HTTP trace log (redacted by default; disable with trace_log_file: "")
├── supernote-user-data/      # Raw uploaded .note, PDF, EPUB, and image files
├── supernote-cache/          # Derived page PNGs and PDF exports (safe to omit from backups)
└── temp/                     # Staging directory for in-flight uploads (auto-cleaned after 24h)
```

Back up `system/supernote.db` and `supernote-user-data/` together so database records stay in sync with files on disk. Use `sqlite3`'s online `.backup` command to take a consistent snapshot without stopping the server:

```bash
sqlite3 storage/system/supernote.db ".backup '/backups/supernote.db'"
rsync -a --delete storage/supernote-user-data/ /backups/supernote-user-data/
rsync -a --delete config/ /backups/config/
```

You can skip `supernote-cache/` and `temp/`; missing cached page PNGs are re-rendered on demand. To check that every database entry matches its file on disk, run:

```bash
supernote admin integrity --full-disk
```
