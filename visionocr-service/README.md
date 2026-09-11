# visionocr-service

A small always-on HTTP wrapper around
[bytefer/macos-vision-ocr](https://github.com/bytefer/macos-vision-ocr) (a
Swift CLI using Apple's Vision framework), so the `supernote-server` fork
running elsewhere (e.g. a VPS or NAS) can get local, free OCR for note
page images instead of calling Gemini. Runs as a `launchd` agent on this Mac,
reachable over Tailscale.

See the root [README](../README.md) for how this fits into the bigger
local-OCR/embeddings architecture.

## Prerequisites

- macOS with Xcode Command Line Tools (`xcode-select --install`).
- Tailscale installed and connected on this Mac (`tailscale ip -4` must
  succeed) — this is what makes the service reachable from the
  `supernote-server` container without opening it up to the public internet.
- Python 3.

## Install

```bash
./install.sh
```

This clones and builds `macos-vision-ocr` (into `.vendor/`, not committed —
it's a separate third-party project), creates a virtualenv, and installs a
`launchd` agent (`~/Library/LaunchAgents/com.supernote.visionocr-service.plist`)
that:

- Runs `run.py`, which binds uvicorn explicitly to `127.0.0.1` and this Mac's
  Tailscale IPv4 address on port `8090` — **never** `0.0.0.0`/all interfaces.
- Starts at login (`RunAtLoad`) and restarts automatically if it crashes
  (`KeepAlive`).
- Logs to `logs/visionocr-service.log` / `logs/visionocr-service.err.log`.

Re-run `./install.sh` any time to rebuild the binary and reload the agent
(e.g. after a `macos-vision-ocr` update).

## Usage

`POST /ocr` with raw image bytes (the `supernote-server` fork posts PNG bytes
it already has in blob storage) and get back the recognized text:

```bash
curl -X POST --data-binary @some-test-image.png http://127.0.0.1:8090/ocr
# {"text": "..."}
```

From another machine on the tailnet:

```bash
curl -X POST --data-binary @some-test-image.png http://<mac-tailscale-ip>:8090/ocr
```

On success (HTTP 200): `{"text": "<recognized text, possibly empty if the
page has no text>"}`. On failure (HTTP 4xx/5xx): `{"error": "...", "detail":
"..."}` — callers should treat this as "OCR failed", not "no text on this
page".

Point the `supernote-server` fork (issue 2) at this service via
`SUPERNOTE_APPLE_VISION_OCR_URL=http://<mac-tailscale-ip>:8090/ocr`.

### Configuration (env vars, set in the plist)

- `VISIONOCR_BINARY` — path to the compiled `macos-vision-ocr` binary.
  Defaults to `bin/macos-vision-ocr` relative to this directory.
- `VISIONOCR_REC_LANGS` — optional comma-separated recognition languages
  (e.g. `en-US`), passed through as `--rec-langs`. Unset means
  `macos-vision-ocr` tries all languages it supports.
- `VISIONOCR_TIMEOUT_SECONDS` — subprocess timeout, default `60`.

## Operational notes

- Implementation detail worth flagging: `macos-vision-ocr --img <path>`
  (single-image mode, no `--output`) prints the OCR result JSON straight to
  stdout and exits `0`; on failure it exits non-zero with an error message on
  stderr. So this service never touches `macos-vision-ocr`'s own `--output`
  flag or reads a JSON file back — it captures stdout/stderr directly and
  only manages its own temp file for the input image. (`master-plan.md`'s
  original sketch assumed reading a written-out JSON file via
  `--output-dir`; that flag doesn't exist for single-image mode, and there's
  no need for it.)
- This only works while the Mac is awake and the service is running. When
  it's not reachable, the caller's OCR step fails for that page and its
  existing retry loop picks it back up once the Mac is reachable again.
- Uninstall: `launchctl unload ~/Library/LaunchAgents/com.supernote.visionocr-service.plist && rm ~/Library/LaunchAgents/com.supernote.visionocr-service.plist`.

## Verifying the acceptance criteria

```bash
launchctl list | grep visionocr
curl -X POST --data-binary @test.png http://127.0.0.1:8090/ocr
curl -X POST --data-binary @test.png http://$(tailscale ip -4):8090/ocr
launchctl kickstart -k gui/$(id -u)/com.supernote.visionocr-service   # simulate a crash
lsof -nP -i :8090   # should show 127.0.0.1:8090 and <tailscale-ip>:8090, never *:8090
```
