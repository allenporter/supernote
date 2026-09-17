# Handoff: Hermes Summary — Production Rollout

Resolves the decisions requested in #6. Prerequisite work (#1–#5) is merged:
`HermesSummaryService` (transport-neutral client), `HermesSummaryModule`
(pipeline registration), metrics/structured logs, and the admin manual-retry
endpoint. This doc records the topology + product-scope decisions for a
given deployment and gives that operator a config plan and verification
steps. Live validation against a real deployment happens in #7, which will
finalize this doc with real command output.

## What Hermes summary actually does

This is not a search feature — semantic search (`search_notebook_chunks`)
already runs over raw OCR text via the local embeddings pipeline, unaffected
by any of this.

Hermes summary is a separate interpretation pass that runs after OCR: it
sends the page's OCR transcript to the operator's own Hermes agent and asks
it to produce a cleaned-up Markdown reading of the page, using whatever
memory/context that agent already has (the operator's own vocabulary,
project names, recurring terms) to resolve ambiguous or garbled OCR —
marking uncertain readings explicitly rather than presenting a guess as
fact. It's stored as its own summary row (`data_source =
HERMES_INTERPRETATION`) alongside the OCR/Gemini summaries in the same
summary group, and already renders in the existing Summary panel
(`SummaryPanel.js` iterates all summaries for a file generically, so no UI
change was needed for it to show up there).

## Decisions (this deployment)

### 1. Deployment topology

**Decision: mounted host path.** `HermesSummaryService` keeps its existing
subprocess-exec transport (`SUPERNOTE_HERMES_SUMMARY_COMMAND` /
`SUPERNOTE_HERMES_SUMMARY_WORKDIR`, unchanged from #2) — no code change to
`HermesSummaryService` is needed for this deployment.

Reasoning: unlike `visionocr-service` (which runs on a separate machine and
is reached over Tailscale HTTP, see `deploy/README.md`), this operator's
Hermes agent CLI runs on the same box as `supernote-server`. That rules out
the webhook/API option (Option B from #6) as unnecessary complexity — there's
no network hop to make thin. It also makes bundling the CLI + its auth/session
state into the `supernote-server` image unnecessary and undesirable (it would
couple Hermes upgrades to `supernote-server` image rebuilds). Instead, the
operator's existing Hermes install is bind-mounted read-write into the
container so the subprocess call in `HermesSummaryService` can exec it
directly, the same way it already does in local development.

Because an unconditional volume mount would break `docker compose up` for
any operator who *doesn't* use Hermes (an empty env var collapses the mount
path to `:/hermes`, which Compose rejects), this is added via a
`docker-compose.override.yml` on the server box, layered on top of the
repo's own `docker-compose.yml` rather than editing that file directly:

```yaml
# docker-compose.override.yml (server box only — not committed to this repo)
services:
  supernote-server:
    volumes:
      - <path-to-your-hermes-install>:/hermes:rw
```

Then in `.env`:

```bash
SUPERNOTE_HERMES_SUMMARY_WORKDIR=/hermes
SUPERNOTE_HERMES_SUMMARY_COMMAND=/hermes/bin/hermes chat -q   # path inside the container, per your install layout
```

Security note, mirroring the posture in `deploy/README.md`'s "Security
notes" section: the mount grants the `supernote-server` container read-write
access to Hermes' own session/auth/memory state. Scope the bind mount to only
the directory Hermes actually needs (not a broader vault or home directory),
consistent with the container's existing "don't grant wider access than the
feature needs" posture.

### 2. Product scope

- **Folder scoping**: runs for **every synced note** with OCR text, matching
  `HermesSummaryModule`'s current (unscoped) behavior — no code change
  needed. Rationale: with the CLI running locally on the same box (no
  network cost), the main cost is Hermes' own response latency per note,
  which is an acceptable tradeoff for this deployment. Revisit later — a
  future `SUPERNOTE_HERMES_SUMMARY_FOLDER`-style scoping config would need
  its own implementation issue if this changes.
- **UI placement**: separate `HERMES_INTERPRETATION` record alongside the
  OCR/AI summary, in the same summary group — this is already
  `HermesSummaryModule`'s existing behavior and already renders in
  `SummaryPanel.js`. No change needed.
- **Corrections**: left entirely to Hermes' own memory/skills. If the
  operator tells Hermes directly (in its own session) that it misread
  something, that correction lives in Hermes' memory and can inform future
  interpretations. No per-note correction metadata is added to Supernote
  itself. Revisit only if this proves insufficient in practice.
- **Response language**: pinned explicitly via
  `SUPERNOTE_HERMES_SUMMARY_LANGUAGE=<your-language>` for this deployment's
  single-language vault, rather than left unset to infer from the
  transcript. Set this in your own `.env` — do not hardcode a literal
  language value in code or in this doc (see repo contribution rules); it's
  an operator-defined config choice.

### 3. Follow-up implementation issues

None. The topology decision does not require a `HermesSummaryService`
transport change (subprocess exec is retained), and the product-scope
decisions above use existing, already-implemented behavior. The only new
work is server-box deployment config (`docker-compose.override.yml`, `.env`),
covered by #7.

## Prerequisites

- #1–#5 merged and released (stable ID helper, `HermesSummaryService`,
  `HermesSummaryModule`, observability, admin retry endpoint).
- Topology decision above made and understood by whoever operates the
  `supernote-server` box (Tailscale-only, per `deploy/README.md`).
- The operator's own Hermes CLI installed and working (`hermes chat -q`
  runnable standalone) somewhere on that same box, outside the container.

## Config to set (`deploy/.env` on the server box — fill in your own values)

```bash
SUPERNOTE_HERMES_SUMMARY_ENABLED=true
SUPERNOTE_HERMES_SUMMARY_COMMAND=/hermes/bin/hermes chat -q   # path as seen inside the container
SUPERNOTE_HERMES_SUMMARY_TIMEOUT_SECONDS=180
SUPERNOTE_HERMES_SUMMARY_WORKDIR=/hermes                      # in-container mount point, see docker-compose.override.yml above
SUPERNOTE_HERMES_SUMMARY_LANGUAGE=<your-language>             # operator-defined; leave unset instead to infer from the transcript
```

Then, with `docker-compose.override.yml` in place (see topology decision
above): `docker compose up -d` — matches the existing "Upgrading to AI mode
later" pattern in `deploy/README.md` for `SUPERNOTE_GEMINI_API_KEY`.

## Verification

Run inside the server container / against its DB:

```bash
docker compose exec supernote-server python3 - <<'PY'
import sqlite3
con = sqlite3.connect('/data/system/supernote.db')  # confirm actual path via SUPERNOTE_STORAGE_DIR
for row in con.execute(
    "select file_id, task_type, status, last_error, update_time "
    "from f_system_task where task_type='HERMES_SUMMARY_GENERATION' "
    "order by update_time desc limit 20"):
    print(row)
PY

docker compose exec supernote-server python3 - <<'PY'
import sqlite3
con = sqlite3.connect('/data/system/supernote.db')
for row in con.execute(
    "select file_id, data_source, length(content), substr(content,1,200) "
    "from f_summary where data_source='HERMES_INTERPRETATION' "
    "order by update_time desc limit 20"):
    print(row)
PY
```

Also check the Prometheus metrics added in #4
(`HERMES_SUMMARY_STARTED_TOTAL`/`COMPLETED_TOTAL`/`FAILED_TOTAL`/
`DURATION_SECONDS`) at `SUPERNOTE_METRICS_PATH` to confirm the module is
actually running, not just configured.

## Acceptance check

Pick any note in your own library that has a known ambiguous/hard-to-read
handwritten phrase, one where you (the operator) know what it should say.
Re-sync it (or use the #5 retry endpoint:
`POST /api/admin/notes/{file_id}/hermes-summary/retry`) and confirm the
interpretation:

- reasonably resolves the ambiguous phrase using whatever session/memory
  context is available to your Hermes agent, and
- marks that resolution as an interpretation, not a fact (uncertainty
  disclosure present).

There's no universal example note for this — it has to be something from
your own vault, since the point is testing against your own Hermes agent's
real memory/context.

Also confirm:

- Re-syncing an unchanged note does not create a duplicate
  `HERMES_INTERPRETATION` row (idempotency, per `HermesSummaryModule`'s
  source-hash check).
- A Hermes call failure (e.g. break the mount path or the command
  temporarily) leaves OCR/embeddings/search working for that note, and the
  `HERMES_SUMMARY_GENERATION` task shows `FAILED` with `last_error`
  populated and is retriable via the #5 endpoint once fixed.

## Rollback

Set `SUPERNOTE_HERMES_SUMMARY_ENABLED=false` and `docker compose up -d`. No
schema rollback needed — Hermes summaries are additive rows with their own
`data_source`. The `docker-compose.override.yml` bind mount can stay in
place harmlessly when disabled (nothing execs into it).
