"""Prometheus metrics definition module for Supernote Private Cloud Server."""

from prometheus_client import Counter, Gauge, Histogram

# HTTP metrics
HTTP_REQUESTS_TOTAL: Counter = Counter(
    "supernote_http_requests_total",
    "Total number of HTTP requests processed.",
    ["method", "path", "status"],
)

HTTP_REQUEST_DURATION_SECONDS: Histogram = Histogram(
    "supernote_http_request_duration_seconds",
    "Latency of HTTP requests in seconds.",
    ["method", "path"],
)

# Processor metrics
PROCESSOR_TASKS_TOTAL: Counter = Counter(
    "supernote_processor_tasks_total",
    "Total number of background pipeline task runs.",
    ["module", "status"],
)

PROCESSOR_TASK_DURATION_SECONDS: Histogram = Histogram(
    "supernote_processor_task_duration_seconds",
    "Latency of background pipeline tasks in seconds.",
    ["module"],
)

PROCESSOR_QUEUE_SIZE: Gauge = Gauge(
    "supernote_processor_queue_size",
    "Current size of the background processor queue.",
)

PROCESSOR_FILES_PROCESSING: Gauge = Gauge(
    "supernote_processor_files_processing",
    "Current number of files actively undergoing background pipeline processing.",
)

PROCESSOR_STALLED_TASKS_RECOVERED_TOTAL: Counter = Counter(
    "supernote_processor_stalled_tasks_recovered_total",
    "Total number of stalled processing tasks recovered.",
)

PROCESSOR_MISSING_TASKS_RECOVERED_TOTAL: Counter = Counter(
    "supernote_processor_missing_tasks_recovered_total",
    "Total number of missing tasks recovered/enqueued.",
)

# Gemini metrics
GEMINI_API_CALLS_TOTAL: Counter = Counter(
    "supernote_gemini_api_calls_total",
    "Total number of Gemini API calls.",
    ["operation", "status"],
)

GEMINI_API_DURATION_SECONDS: Histogram = Histogram(
    "supernote_gemini_api_duration_seconds",
    "Latency of Gemini API calls in seconds.",
    ["operation"],
)

# Hermes summary metrics
HERMES_SUMMARY_STARTED_TOTAL: Counter = Counter(
    "supernote_hermes_summary_started_total",
    "Total number of Hermes summary generation attempts started.",
)

HERMES_SUMMARY_COMPLETED_TOTAL: Counter = Counter(
    "supernote_hermes_summary_completed_total",
    "Total number of Hermes summary generations completed successfully.",
)

HERMES_SUMMARY_FAILED_TOTAL: Counter = Counter(
    "supernote_hermes_summary_failed_total",
    "Total number of Hermes summary generation failures.",
)

HERMES_SUMMARY_DURATION_SECONDS: Histogram = Histogram(
    "supernote_hermes_summary_duration_seconds",
    "Latency of Hermes summary generation attempts in seconds.",
)

# Recycle bin cleanup metrics
RECYCLE_BIN_CLEANUP_RUNS_TOTAL: Counter = Counter(
    "supernote_recycle_bin_cleanup_runs_total",
    "Total number of scheduled recycle bin cleanup job runs.",
    ["status"],
)

RECYCLE_BIN_CLEANUP_ITEMS_PURGED_TOTAL: Counter = Counter(
    "supernote_recycle_bin_cleanup_items_purged_total",
    "Total number of files permanently purged by the recycle bin cleanup job.",
)

RECYCLE_BIN_CLEANUP_DURATION_SECONDS: Histogram = Histogram(
    "supernote_recycle_bin_cleanup_duration_seconds",
    "Latency of recycle bin cleanup job runs in seconds.",
)

# Database metrics
DB_SESSIONS_ACTIVE: Gauge = Gauge(
    "supernote_db_sessions_active",
    "Current number of active/open database sessions.",
)

DB_SESSION_ERRORS_TOTAL: Counter = Counter(
    "supernote_db_session_errors_total",
    "Total number of database session errors causing rollbacks.",
)
