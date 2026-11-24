"""LLM Wiki server component (`WikiComponent`).

Implements a hybrid *"compile once, query cheaply"* personal knowledge base over
handwritten Supernote notebooks (`NotePageTranscribedEvent`, `NotePagesDeltaEvent`)
and Schedule tasks (`ScheduleTask*Event`), decoupled from `SummaryModule` and
`VirtualFileSystem` (see `docs/adr/0002-llm-wiki-architecture.md`).

### Design Principles & Research Grounding

- **Background consolidation, cheap queries** (*Karpathy LLM Wiki*, *Letta Memory
  Blocks*, *Sleep-time Compute*): Offloads cross-notebook synthesis to debounced
  per-user background passes (`WikiCompilerWorker`) driven by `f_user_event`
  cursors while keeping query lookups deterministic and compact via `index`,
  `f_wiki_alias`, and `f_wiki_link`.
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

### Two-Tier Lint Issues (`f_wiki_lint_issue`)

Wiki hygiene is split into two tiers whose findings are stored idempotently per
`(user_id, dedup_key)` in `f_wiki_lint_issue` (`status`: `open`, `resolved`, or
`dismissed`):

1. **Tier A — Zero-LLM Structural Lint (`WikiService.run_structural_lint`, runs
   free after every compile):**
   - `broken_link` (`warn`): Active page contains a `[[wikilink]]` whose target
     slug has no active page (`target_page_id is None`).
   - `orphan_page` (`info`): Active non-`index`/`log` page has no inbound links
     from other active pages (self-links do not count).
   - `stale_source` (`warn`): Active page cites a deleted note page, file, or
     schedule task (`f_wiki_source_ref.is_source_deleted = True`).
   - Open Tier A issues automatically transition to `resolved` once the underlying
     condition is fixed, while `dismissed` issues remain suppressed.
2. **Tier B — Bounded LLM Semantic Lint (`WikiCompilerWorker.run_semantic_lint`
   and compile-time `lint_proposals`):**
   - `contradiction` (`warn`): Conflicting active claims across wiki pages or
     against current `ScheduleTaskDO` states.
   - `alias_merge_proposal` (`warn`): Suspected handwriting-OCR duplicate entities
     (e.g. `Al1ce` vs `Alice`) quarantined with a suggested `proposal_json` target
     for explicit human or agent confirmation—never silently auto-merged.

Registered opt-in (`default_enabled=False`) in `BUILTIN_COMPONENTS`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supernote.server.components.ai import TEXT_MODEL_KEY
from supernote.server.components.events.service import EVENT_LOG_SERVICE_KEY
from supernote.server.core import ServerCore

from .compiler import WIKI_COMPILER_KEY, WikiCompilerWorker
from .config import WikiConfig
from .export import WIKI_EXPORT_SERVICE_KEY, WikiExportService
from .service import WIKI_SERVICE_KEY, WikiService

__all__ = [
    "WIKI_COMPILER_KEY",
    "WIKI_EXPORT_SERVICE_KEY",
    "WIKI_SERVICE_KEY",
    "WikiCompilerWorker",
    "WikiComponent",
    "WikiConfig",
    "WikiExportService",
    "WikiService",
]


class WikiComponent:
    """Vertical component managing per-user LLM wiki storage, export, and compilation."""

    domain = "wiki"
    dependencies: tuple[str, ...] = ("ai", "events")
    platforms: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._config: WikiConfig | None = None
        self._compiler: WikiCompilerWorker | None = None

    @property
    def config(self) -> WikiConfig | None:
        """Validated `WikiConfig` after `async_setup`."""
        return self._config

    async def async_setup(self, core: ServerCore, config: Mapping[str, Any]) -> None:
        """Validate `WikiConfig`, instantiate services, and expose app keys."""
        self._config = WikiConfig.from_dict(config)
        service = WikiService(core.session_manager)
        compiler = WikiCompilerWorker(
            config=self._config,
            session_manager=core.session_manager,
            wiki_service=service,
            event_log_service=core.app[EVENT_LOG_SERVICE_KEY],
            event_bus=core.event_bus,
            text_model=core.app.get(TEXT_MODEL_KEY),
        )
        self._compiler = compiler
        core.app[WIKI_SERVICE_KEY] = service
        core.app[WIKI_EXPORT_SERVICE_KEY] = WikiExportService(service)
        core.app[WIKI_COMPILER_KEY] = compiler

    async def async_start(self, core: ServerCore) -> None:
        """Bind finalized `TEXT_MODEL_KEY` and start event subscriptions."""
        if self._compiler is not None:
            self._compiler.set_text_model(core.app.get(TEXT_MODEL_KEY))
            await self._compiler.start()

    async def async_stop(self, core: ServerCore) -> None:
        """Idempotently stop background debounce timers and release references."""
        compiler = self._compiler
        self._compiler = None
        self._config = None
        if compiler is not None:
            await compiler.stop()
