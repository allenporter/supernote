"""Core domain and infrastructure services for the Supernote Private Cloud server.

Each service encapsulates a distinct domain boundary and communicates with other
services either through explicit dependency injection in `supernote.server.app.create_app`
or asynchronously via `supernote.server.events.LocalEventBus`.

| Service Class | Module | Responsibility |
| :--- | :--- | :--- |
| `supernote.server.services.file.FileService` | `supernote.server.services.file` | High-level file, folder, upload/download, and recycle bin orchestration. |
| `supernote.server.services.vfs.VirtualFileSystem` | `supernote.server.services.vfs` | Transactional SQLite-backed directory tree and path resolution (`UserFileDO`). |
| `supernote.server.services.blob.LocalBlobStorage` | `supernote.server.services.blob` | Content-addressable blob storage (`USER_DATA_BUCKET` and `CACHE_BUCKET`). |
| `supernote.server.services.processor.ProcessorService` | `supernote.server.services.processor` | Asynchronous 5-stage `.note` processing pipeline and task recovery loop. |
| `supernote.server.services.conversion.ConversionService` | `supernote.server.services.conversion` | On-demand `.note` to PNG and vector PDF conversion with cache lookup. |
| `supernote.server.components.search.service.SearchService` | `supernote.server.components.search.service` | Semantic vector similarity search and notebook transcript retrieval. |
| `supernote.server.services.summary.SummaryService` | `supernote.server.services.summary` | CRUD and tag management for AI and handwritten summaries (`SummaryDO`). |
| `supernote.server.components.schedule.service.ScheduleService` | `supernote.server.components.schedule.service` | Task groups, tasks, recurrence rules, and delta synchronization. |
| `supernote.server.components.schedule.ical_export.ICalExportService` | `supernote.server.components.schedule.ical_export` | RFC 5545 `VTODO` iCalendar (`.ics`) feed generation from schedule tasks. |
| `supernote.server.components.webhooks.service.WebhookService` | `supernote.server.components.webhooks.service` | Non-blocking, HMAC-SHA256 signed outbound HTTP webhook dispatcher. |
| `supernote.server.services.integrity.IntegrityService` | `supernote.server.services.integrity` | Two-way consistency verification between SQLite VFS metadata and disk blobs. |
| `supernote.server.services.coordination.SqliteCoordinationService` | `supernote.server.services.coordination` | TTL-backed key-value store and distributed locks (`KeyValueDO`). |
| `supernote.server.services.user.UserService` | `supernote.server.services.user` | User accounts, Admin-First bootstrap, static API keys, device bindings, and JWT sessions. |
| `supernote.server.components.events.service.EventLogService` | `supernote.server.components.events.service` | Append-only per-user domain event log (`UserEventDO`), cursor pagination, and retention pruning. |
| `supernote.server.components.metrics.storage.StorageMetricsCollector` | `supernote.server.components.metrics.storage` | Periodic background collector for blob storage and cache Prometheus gauges. |

See `supernote.guides.architecture` for the end-to-end service interaction model.
"""

__all__ = [
    "blob",
    "conversion",
    "coordination",
    "file",
    "integrity",
    "processor",
    "processor_modules",
    "summary",
    "user",
    "vfs",
    "webhook",
]
