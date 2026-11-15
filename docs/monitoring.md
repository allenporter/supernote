# Prometheus Monitoring & Grafana Dashboard

Open Private Cloud for Supernote exposes operational metrics in Prometheus format at `/metrics` (when `metrics_enabled: true` in `config.yaml`, enabled by default).

Reference monitoring assets are included in [`docs/monitoring/`](./monitoring/):

- [`docs/monitoring/grafana_dashboard.json`](./monitoring/grafana_dashboard.json): Reference Grafana dashboard (**Open Private Cloud for Supernote**) querying raw `/metrics` series directly without requiring recording rules.
- [`docs/monitoring/prometheus_rules.yaml`](./monitoring/prometheus_rules.yaml): Optional recording rules (`supernote_recording_rules`) and alerting rules (`supernote_alerting_rules`).

---

## Server & Prometheus Setup

### Server Configuration (`config.yaml`)

```yaml
metrics_enabled: true
metrics_path: /metrics
```

### Prometheus Scrape & Rule Configuration (`prometheus.yml`)

Copy [`docs/monitoring/prometheus_rules.yaml`](./monitoring/prometheus_rules.yaml) into your Prometheus rules directory and reference it under `rule_files`:

```yaml
rule_files:
  - /etc/prometheus/rules/prometheus_rules.yaml

scrape_configs:
  - job_name: supernote
    metrics_path: /metrics
    scrape_interval: 15s
    static_configs:
      - targets: ["supernote:8080"]
```

### Grafana Import

1. In Grafana, navigate to **Dashboards $\rightarrow$ New $\rightarrow$ Import**.
2. Upload [`docs/monitoring/grafana_dashboard.json`](./monitoring/grafana_dashboard.json).
3. Select your Prometheus data source for `DS_PROMETHEUS` and click **Import**.

---

## Exported Metric Catalog

| Metric Family | Type | Labels | Description |
| :--- | :---: | :--- | :--- |
| `supernote_http_requests_total` | Counter | `method`, `path`, `status` | HTTP requests processed (unmatched paths collapse to `HTTP <status>`; non-standard verbs map to `OTHER`; client disconnects record `status="499"`). |
| `supernote_http_request_duration_seconds` | Histogram | `method`, `path` | Completed HTTP request latency (`REQUEST_DURATION_BUCKETS` up to `300s`). |
| `supernote_mcp_tool_calls_total` | Counter | `tool`, `status` | MCP server tool invocations (`list_notebooks`, `search_notebook_chunks`, `get_notebook_transcript`). |
| `supernote_mcp_tool_duration_seconds` | Histogram | `tool` | Completed MCP tool latency (`REQUEST_DURATION_BUCKETS` up to `300s`). |
| `supernote_db_session_errors_total` | Counter | — | Database and SQLAlchemy session errors. |
| `supernote_processor_queue_size` | Gauge | — | Files currently waiting in the background processor queue. |
| `supernote_processor_queue_paused` | Gauge | — | `1` when background queue execution is paused, `0` when active. |
| `supernote_processor_tasks_total` | Counter | `module`, `status` | Per-module task executions (`success`, `failure`, `skipped`, `cancelled`). |
| `supernote_processor_task_duration_seconds` | Histogram | `module` | Completed task latency (`PIPELINE_DURATION_BUCKETS` up to `600s`; excludes `skipped`/`cancelled`). |
| `supernote_processor_stalled_tasks_recovered_total` | Counter | — | Stalled `PROCESSING` tasks recovered on startup/sweep. |
| `supernote_processor_missing_tasks_recovered_total` | Counter | — | Missing processing tasks enqueued by integrity recovery. |
| `supernote_note_processing_runs_total` | Counter | `mode`, `status` | End-to-end `.note` pipeline runs (`mode`: `full` or `on_demand`; `status`: `success`, `failure`, `cancelled`). |
| `supernote_note_processing_duration_seconds` | Histogram | `mode` | Completed `.note` pipeline run latency (`PIPELINE_DURATION_BUCKETS` up to `600s`). |
| `supernote_note_pages_parsed_total` | Counter | `change_type` | Pages reconciled during `PageHashingModule` (`added`, `modified`, `moved`, `unchanged`, `deleted`). |
| `supernote_ai_requests_total` | Counter | `provider`, `model`, `stage`, `status` | Logical AI invocations across `ocr`, `summary`, `embedding_doc`, and `embedding_query`. |
| `supernote_ai_request_duration_seconds` | Histogram | `provider`, `model`, `stage` | Completed AI call latency (`PIPELINE_DURATION_BUCKETS` up to `600s`). |
| `supernote_ai_tokens_total` | Counter | `provider`, `model`, `stage`, `token_type` | Disjoint AI token counts (`input`, `output`, `thinking`). |
| `supernote_note_uploads_total` | Counter | `source` | Completed `.note` uploads (`device_sync`, `web`). |
| `supernote_oss_transfer_bytes_total` | Counter | `direction`, `kind` | OSS payload bytes transferred (`user_blob`, `user_chunk`, `png_preview`, `pdf_export`). |
| `supernote_blob_storage_objects` | Gauge | `bucket`, `kind` | Stored blob object count (`user_blob`, `png`, `pdf`), refreshed every 5 minutes. |
| `supernote_blob_storage_bytes` | Gauge | `bucket`, `kind` | Stored blob byte totals (`user_blob`, `png`, `pdf`), refreshed every 5 minutes. |
| `supernote_blob_storage_available_bytes` | Gauge | — | Available free bytes on the storage volume backing blob storage. |
