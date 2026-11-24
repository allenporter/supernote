"""LLM Wiki server component (`WikiComponent`).

Implements a hybrid *"compile once, query cheaply"* personal knowledge base over
handwritten Supernote notebooks (`NotePageTranscribedEvent`, `NotePagesDeltaEvent`)
and Schedule tasks (`ScheduleTask*Event`), decoupled from `SummaryModule` and
`VirtualFileSystem` (see `docs/adr/0002-llm-wiki-architecture.md`).

### Design Principles & Research Grounding

- **Background consolidation, cheap queries** (*Karpathy LLM Wiki*, *Letta Memory
  Blocks*, *Sleep-time Compute*): Offloads cross-notebook synthesis to debounced
  per-user background passes driven by `f_user_event` cursors while keeping query
  lookups deterministic and compact via `index`, `f_wiki_alias`, and `f_wiki_link`.
- **Bi-temporal, non-destructive history** (*Zep/Graphiti* vs. *Mem0*): Every page
  mutation records an immutable `f_wiki_revision` snapshot and supersedes claims
  rather than destructively deleting prior facts. User edits flip pages to
  `edit_policy="protected_prose"` so automated writers never clobber human prose.
- **Local incremental updates over global batch clustering** (*LightRAG* vs.
  *RAPTOR* / *MS GraphRAG*): Updates only the small neighborhood of pages touched
  by incoming page/task diffs rather than rebuilding static cluster trees.
- **Passage-grounded provenance** (*HippoRAG 2*): Every compiled page tracks
  verbatim `f_wiki_source_ref` bindings (`note_page:{file_id}:{page_id}`,
  `schedule_task:{task_id}`) so queries pair synthesized wiki pages with raw notes.
- **Conservative handwriting-OCR entity hygiene** (*OHRBench*): Unambiguous aliases
  resolve via `f_wiki_alias`, while ambiguous OCR duplicates are quarantined as
  reviewable `f_wiki_lint_issue` proposals rather than silently auto-merged.
- **Out-of-VFS SQLite storage & Obsidian export**: Persists multi-user state in
  `f_wiki_*` tables (never polluting hardware tablet VFS sync or quotas) and
  streams Obsidian-compatible Markdown / `.zip` vaults on demand via
  `WikiExportService`.

Registered opt-in (`default_enabled=False`) in `BUILTIN_COMPONENTS`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.core import ServerCore

from .config import WikiConfig
from .export import WIKI_EXPORT_SERVICE_KEY, WikiExportService
from .service import WIKI_SERVICE_KEY, WikiService

__all__ = [
    "WIKI_EXPORT_SERVICE_KEY",
    "WIKI_SERVICE_KEY",
    "WikiComponent",
    "WikiConfig",
    "WikiExportService",
    "WikiService",
]


class WikiComponent:
    """Vertical component managing per-user LLM wiki storage and export."""

    domain = "wiki"
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._config: WikiConfig | None = None

    @property
    def config(self) -> WikiConfig | None:
        """Validated `WikiConfig` after `async_setup`."""
        return self._config

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Validate `WikiConfig`, instantiate services, and expose app keys."""
        self._config = WikiConfig.from_dict(config)
        service = WikiService(core.session_manager)
        core.app[WIKI_SERVICE_KEY] = service
        core.app[WIKI_EXPORT_SERVICE_KEY] = WikiExportService(service)

    async def async_start(self, core: ServerCore) -> None:
        """No-op; background compilation worker attaches in PR 4."""

    async def async_stop(self, core: ServerCore) -> None:
        """Idempotently release component state."""
        self._config = None
