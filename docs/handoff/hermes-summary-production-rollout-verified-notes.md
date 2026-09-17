# Hermes summary production rollout — verified notes

This file records the real production rollout pattern verified during issue #7. Keep deployment-specific hostnames, private note names, and secrets out of committed docs; replace them with placeholders when adapting elsewhere.

## Production config applied

On the server box, keep the repository `docker-compose.yml` generic and add the Hermes-specific host mounts in a local-only `docker-compose.override.yml`:

```yaml
services:
  supernote-server:
    environment:
      HERMES_HOME: /hermes-home
    volumes:
      - <host-hermes-install-dir>:/usr/local/lib/hermes-agent:ro
      - <host-hermes-bin>:/usr/local/bin/hermes:ro
      - <host-python-runtime-dir>:/opt/hermes-python-runtime:ro
      - <host-hermes-state-dir>:/hermes-home:rw
      - ./hermes-summary-wrapper.sh:/usr/local/bin/hermes-summary-wrapper:ro
```

If the container image runs as an unprivileged UID and the Hermes state lives under a root-only home directory, either grant a narrow ACL for that UID or run the container with an explicit local override such as `user: "0:0"`. Prefer an ACL where available; the verified deployment used a local override because the server did not have ACL tooling installed.

## Wrapper note

The wrapper is needed for Hermes CLI versions where `hermes chat -q` requires the query as an argument rather than reading it from stdin. `HermesSummaryService` passes the prompt via stdin, so the wrapper bridges that interface:

```bash
#!/usr/bin/env bash
set -euo pipefail
prompt=$(cat)
output=$(/usr/local/bin/hermes chat -Q --toolsets safe --source supernote-hermes-summary -q "$prompt")
python3 - "$output" <<'PY'
import re, sys
text = sys.argv[1]
text = re.split(r'\n\s*Resume this session with:', text, maxsplit=1)[0]
text = re.split(r'\n\s*Session:\s+', text, maxsplit=1)[0]
lines = [line for line in text.splitlines() if not line.strip().startswith('session_id:')]
print('\n'.join(lines).strip())
PY
```

## Environment

Production `.env` additions:

```bash
SUPERNOTE_HERMES_SUMMARY_ENABLED=true
SUPERNOTE_HERMES_SUMMARY_COMMAND=/usr/local/bin/hermes-summary-wrapper
SUPERNOTE_HERMES_SUMMARY_TIMEOUT_SECONDS=240
SUPERNOTE_HERMES_SUMMARY_WORKDIR=/tmp
SUPERNOTE_HERMES_SUMMARY_LANGUAGE=<operator-language>
HERMES_HOME=/hermes-home
```

After `docker compose up -d --build`, startup logs should include:

```text
Hermes Summary Enabled: True
Using SUPERNOTE_HERMES_SUMMARY_COMMAND: /usr/local/bin/hermes-summary-wrapper
Using SUPERNOTE_HERMES_SUMMARY_TIMEOUT_SECONDS: 240
Using SUPERNOTE_HERMES_SUMMARY_WORKDIR: /tmp
Using SUPERNOTE_HERMES_SUMMARY_LANGUAGE: <operator-language>
Database migrations complete.
Application startup complete.
Startup sequence complete.
```

## Manual retry / validation

Use the admin retry endpoint to validate one real note with OCR text:

```http
POST /api/admin/notes/<file_id>/hermes-summary/retry
```

Expected response shape:

```json
{
  "success": true,
  "fileId": "<file_id>",
  "task": {
    "taskType": "HERMES_SUMMARY_GENERATION",
    "status": "PENDING",
    "lastError": null
  }
}
```

Then verify the DB:

```bash
docker compose exec supernote-server python3 - <<'PY'
import sqlite3
con = sqlite3.connect('/data/system/supernote.db')
for row in con.execute(
    "select file_id,status,last_error "
    "from f_system_task where task_type='HERMES_SUMMARY_GENERATION' "
    "order by update_time desc limit 10"):
    print(row)
for row in con.execute(
    "select file_id,data_source,length(content),substr(content,1,200) "
    "from f_summary where data_source='HERMES_INTERPRETATION' "
    "order by update_time desc limit 10"):
    print(row)
PY
```

Verified successful result:

```text
HERMES_SUMMARY_GENERATION -> COMPLETED
f_summary.data_source='HERMES_INTERPRETATION'
summary content is Markdown in the configured language
uncertain OCR readings are explicitly marked as uncertain
```

## Idempotency check

Run the same retry endpoint for the same unchanged note twice. Verified result:

```text
before: one HERMES_INTERPRETATION row with stable unique_identifier
after:  one HERMES_INTERPRETATION row with the same row id and unique_identifier
```

## Failure isolation check

Temporarily set the command to a failing executable and restart:

```bash
SUPERNOTE_HERMES_SUMMARY_COMMAND=/bin/false
docker compose up -d
```

Retry a note with existing OCR and embedding. Verified result:

```text
HERMES_SUMMARY_GENERATION -> FAILED
last_error starts with: Hermes summary CLI exited with code 1
OCR text remains present for the note
embedding remains present for the note
no HERMES_INTERPRETATION row is created while the command is broken
```

Restore the wrapper command and restart:

```bash
SUPERNOTE_HERMES_SUMMARY_COMMAND=/usr/local/bin/hermes-summary-wrapper
docker compose up -d
POST /api/admin/notes/<file_id>/hermes-summary/retry
```

The retried task should reach `COMPLETED` and create/update a single `HERMES_INTERPRETATION` row.

## Metrics check

While the process is still running, check:

```bash
curl -sS http://127.0.0.1:8080/metrics | grep -E 'supernote_hermes_summary_(started|completed|failed|duration)'
```

Expected metrics include:

```text
supernote_hermes_summary_started_total
supernote_hermes_summary_completed_total
supernote_hermes_summary_failed_total
supernote_hermes_summary_duration_seconds
```

Prometheus counters are process-local and reset when the container restarts; use DB task rows and logs as the durable audit trail.
