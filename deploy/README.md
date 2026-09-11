# Supernote Private Cloud — deployment

Self-hosted [Supernote Private Cloud](https://support.supernote.com/Whats-New/setting-up-your-own-supernote-private-cloud-beta)
server, built from [striimusMiska/supernote](https://github.com/striimusMiska/supernote)
(a fork of [allenporter/supernote](https://github.com/allenporter/supernote)),
deployed on the [REDACTED-HOST] box where the [REDACTED-AGENT] agent lives, reachable only over
the existing Tailscale tunnel. OCR transcription and semantic search run
locally — no Gemini key needed for those, see "OCR and semantic search
architecture" below. AI summaries are a separate, still-optional feature;
add `SUPERNOTE_GEMINI_API_KEY` later to turn those on.

## Deploy

1. On the [REDACTED-HOST] box, find its Tailscale address:
   ```bash
   tailscale ip -4
   ```
2. Clone the fork onto the box, at a pinned tag/commit — not a moving
   `main` — since `docker compose build` here builds `supernote-server`
   from this checkout (build context is the repo root, one level above
   `deploy/`):
   ```bash
   git clone https://github.com/striimusMiska/supernote.git
   cd supernote
   git checkout <pinned-tag-or-commit>
   cd deploy
   ```
   Then create `.env`:
   ```bash
   cp .env.example .env
   ```
   Fill in:
   - `TAILSCALE_IP` — the address from step 1.
   - `SUPERNOTE_BASE_URL` / `SUPERNOTE_MCP_BASE_URL` — HTTPS Tailscale Serve
     URLs. Current MCP OAuth requires an HTTPS issuer, so use e.g.
     `https://<node>.<tailnet>.ts.net:8443` and `:8444`, not plain
     `http://<tailscale-ip>`.
   - `SUPERNOTE_JWT_SECRET` — generate once with `openssl rand -hex 32` and
     never regenerate it. Without this, the server picks a random secret on
     every restart, which silently logs out the Nomad's sync and any MCP
     OAuth session each time the container restarts.
   - `APPLE_VISION_OCR_URL` — the Mac's Tailscale IP + port 8090, where
     `visionocr-service` (issue #1) listens.
   Configure Tailscale Serve before starting the container:
   ```bash
   tailscale serve --bg --https=8443 http://127.0.0.1:8080
   tailscale serve --bg --https=8444 http://127.0.0.1:8081
   tailscale serve status
   ```
3. Start it:
   ```bash
   docker compose up -d --build
   docker compose logs -f supernote-server   # confirm it's listening
   ```
   Then pull the embedding model into the new `ollama` service (one-time;
   the named volume persists it across restarts):
   ```bash
   docker compose exec ollama ollama pull bge-m3
   ```
4. Create your admin account:
   ```bash
   docker compose exec supernote-server \
     supernote admin --url http://localhost:8080 user add you@example.com
   ```
5. (Optional, for CLI use) Log in from wherever you'll run the CLI:
   ```bash
   supernote cloud login you@example.com --url http://<tailscale-ip>:8080
   ```
   Running `supernote cloud login` or `supernote admin ... user reset-password`
   *inside the container* (`docker compose exec supernote-server ...`) needs a
   writable `$HOME` for the `supernote` user to cache its session
   (`~/.cache/supernote.pkl`) — fixed in this `Dockerfile` by adding `-m` to
   `useradd`. If you're running against an older built image that predates
   that fix, add `-u root` to the `docker compose exec` call as a one-off
   workaround (both the `login` and the following admin call need it, so the
   credential cache lands in the same place), or `docker compose up -d --build`
   to rebuild with the fix.
   
   The Nomad's Private Cloud password field also has a low max length — if
   your generated admin password doesn't fit, reset it to something shorter
   via `supernote admin ... user reset-password <email> --password <short-pw>`
   (requires being logged in first, per above).

## Connect the Nomad

The tablet isn't on the same LAN as the [REDACTED-HOST] box, so it needs to join the
tailnet too:

1. On the Nomad: **Settings → Security & Privacy → Sideloading** → enable.
2. Install the Tailscale Android app (via F-Droid/Aurora Store, or sideload
   the APK directly) and log into the same tailnet.
3. On the Nomad: **Settings → Sync → Private Cloud** → server address
   `<node>.<tailnet>.ts.net:8443` (the Tailscale Serve hostname, same as the
   MCP endpoint below — use the full `https://...` form if the field rejects
   a bare host:port) → log in with the account from step 4 above. The direct
   `<tailscale-ip>:8080` binding also still works if the device needs plain
   HTTP.
4. **Settings → Drive → Private Cloud** → pick folders to sync (e.g. `Note`,
   `Document`, `EXPORT`).

## Connect agents (MCP)

The server exposes an MCP endpoint on port 8081 with two tools:
`search_notebook_chunks` and `get_notebook_transcript`. Both work once OCR
and embeddings have run over synced pages — see "OCR and semantic search
architecture" below.

- **[REDACTED-AGENT]** (same box): `https://<node>.<tailnet>.ts.net:8444/mcp` with
  `auth: oauth` in `~/.[REDACTED-AGENT]/config.yaml` / `[REDACTED-AGENT] mcp add --auth oauth`.
- **Claude Desktop / Claude Code** (your Mac, over Tailscale):
  `https://<node>.<tailnet>.ts.net:8444/mcp`, either via the `mcp-proxy` wrapper (see
  the [upstream MCP docs](https://github.com/allenporter/supernote/blob/main/docs/mcp.md))
  or a direct URL-type MCP server entry if your client supports it.
  First connection redirects to the server's login page for OAuth 2.1
  authorization (dynamic client registration — no pre-registration needed).

  **Claude Code specifically** doesn't support this server's IndieAuth-style
  client identification out of the box (it expects RFC 7591 dynamic client
  registration, which the server doesn't implement — see
  `supernote/server/mcp/auth.py`). Work around it by pinning the OAuth client
  identity to match the fixed callback URL Claude Code uses:
  ```bash
  claude mcp add --transport http --scope user \
    --client-id "http://localhost:3118/callback" \
    --callback-port 3118 \
    supernote https://<node>.<tailnet>.ts.net:8444/mcp
  claude mcp login supernote   # must run in a real interactive terminal
  ```
  The server only accepts a redirect URI that *starts with* the `client_id`
  string (its `get_client()` treats an IndieAuth client's own URL as its one
  allowed redirect URI) — if `client_id` doesn't match the callback Claude
  Code actually uses, you'll get `Redirect URI '...' not in allowed list`.

  **Even with that fixed, `claude mcp login supernote` will still time out.**
  The server-side bridge (`supernote/server/mcp/auth.py`, `login_bridge()`)
  is built expecting the web UI to, after login, POST to `/login-bridge`
  with an `x-access-token` header and then redirect the browser to the
  returned `redirect_url`. The current web UI (`static/js/main.js`,
  `handleLogin()`) doesn't implement that at all — it just logs you in and
  navigates to `#/files`, so the OAuth flow can never complete on its own.
  This is a bug in the upstream project, worth filing there.

  Manual workaround until it's fixed upstream:
  1. Run `claude mcp login supernote`; copy the full `/authorize?...` URL
     it prints (don't let it time out — do the next steps promptly).
  2. Log into the web UI in a browser if you aren't already, then in
     DevTools → Console run `localStorage.getItem('supernote_token')` to
     get a session token.
  3. Replace `/authorize` with `/login-bridge` in the copied URL, keep the
     same query string, and POST it with that token:
     ```bash
     curl -s -X POST "https://<node>.<tailnet>.ts.net:8443/login-bridge?<same query string, URL-encoded>" \
       -H "x-access-token: <token>"
     ```
     This returns `{"redirect_url": "http://localhost:<port>/callback?code=...&state=..."}`.
  4. `curl` that `redirect_url` (or open it in a browser) — it hits Claude
     Code's local loopback listener directly and completes the login.

## OCR and semantic search architecture

OCR transcription and semantic search no longer go through Gemini — both
run locally instead:

- **OCR** runs on [REDACTED-NAME]'s Mac via `visionocr-service` (issue #1), a small
  HTTP wrapper around Apple's Vision framework. The server calls it at
  `APPLE_VISION_OCR_URL` (the Mac's Tailscale IP, port 8090) to populate
  `text_content` for each synced page — this alone is what
  `get_notebook_transcript` needs.
- **Embeddings** run via the `ollama` service added to `docker-compose.yml`
  (image `ollama/ollama`, `bge-m3` model), reachable only from
  `supernote-server` at `http://ollama:11434` over the compose network's own
  DNS — no port is published to the host or Tailscale. This populates the
  `embedding` column that `search_notebook_chunks` does cosine similarity
  over, and also embeds the query itself at search time.
- This **replaces** the Gemini-based OCR/embedding path entirely. Gemini
  (`SUPERNOTE_GEMINI_API_KEY`) is now only relevant if/when AI summaries
  (`SummaryModule`) get turned on separately — see "Upgrading to AI mode
  later" below.
- Operational tradeoff: OCR only works while the Mac is awake and
  `visionocr-service` is running. When it's not reachable, the OCR task for
  that page fails and the server's existing stalled-task recovery retries
  it automatically (every 5 min) — no manual intervention needed once the
  Mac is reachable again.

## Security notes

- Ports are bound to `127.0.0.1` and `${TAILSCALE_IP}` explicitly in
  `docker-compose.yml`, **not** `0.0.0.0` — this is the actual boundary
  keeping the server off the public internet. Don't "simplify" this to
  `0.0.0.0:8080:8080` and rely on a `ufw` rule instead: Docker inserts its own
  iptables rules ahead of ufw's, so a ufw allow/deny rule can silently fail to
  apply to a container's published port.
- The `ollama` service publishes **no** ports at all — it's reachable only
  from `supernote-server` over the compose network's internal DNS. Don't add
  a `ports:` entry to it.
- Verify from your Mac with Tailscale disconnected that
  `curl http://<[REDACTED-HOST]-public-ip>:8080` times out.
- The `tailscale serve` commands above publish tailnet-only by default —
  don't substitute `tailscale funnel`, which exposes to the public internet
  and would undo the whole point of this setup.

## Upgrading to AI mode later

OCR/embeddings/search are already on by default (see above) — this section
is now only about AI-generated summaries. Set `SUPERNOTE_GEMINI_API_KEY` in
`.env`, then `docker compose up -d` to restart with it picked up. No other
config changes needed.
