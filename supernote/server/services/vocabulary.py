"""Per-user vocabulary that biases transcription toward the spellings a person uses."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.extended import VocabularySource
from supernote.server.constants import CATEGORY_CONTAINERS
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.vocabulary import ROOT_SCOPE_ID, VocabularyTermDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import Event, NoteDeletedEvent
from supernote.server.exceptions import FileNotFound, VocabularyTermNotFound
from supernote.server.services.vfs import VirtualFileSystem
from supernote.server.utils.common_words import is_common

__all__ = [
    "MAX_HARVEST_WORDS",
    "MAX_PROMPT_TERMS",
    "MAX_TERM_LENGTH",
    "VocabularyService",
    "VocabularyTerm",
]

logger = logging.getLogger(__name__)

MAX_PROMPT_TERMS = 200
"""Most terms offered to one prompt; a long list dilutes the instruction."""

MAX_TERM_LENGTH = 64
"""Longest accepted term; device keywords can be whole sentences."""

MAX_HARVEST_WORDS = 4
"""Longest harvested keyword in words; longer ones are notes, not spellings."""

_MAX_FOLDER_DEPTH = 64

# Stripped from both ends of a harvested keyword. Periods are kept so that
# initialisms such as `U.N.` survive.
_EDGE_PUNCTUATION = "-_!?,;:#*\"'`()[]{}<>/\\|~–— "


@dataclass(frozen=True)
class VocabularyTerm:
    """A term as seen by callers of `VocabularyService`."""

    id: int
    term: str
    scope_id: int
    source: VocabularySource
    create_time: int
    is_suppressed: bool = False
    origin_file_id: int | None = None
    """Notebook a harvested term was first found in."""

    scope_path: str = ""
    """Folder or notebook the term applies to, e.g. `Note/Work`; empty for every notebook."""

    origin_name: str | None = None
    """File name of `origin_file_id`, if that notebook still exists."""


def _normalize(term: str) -> str:
    return " ".join(term.split())


def _clean_keyword(keyword: str) -> str | None:
    """Return a device keyword as a term, or None if it would not help OCR."""
    term = _normalize(keyword).strip(_EDGE_PUNCTUATION)
    if (
        not any(c.isalpha() for c in term)
        or len(term) > MAX_TERM_LENGTH
        or len(term.split()) > MAX_HARVEST_WORDS
        or is_common(term)
    ):
        return None
    return term


class VocabularyService:
    """Stores vocabulary terms and resolves the ones that apply to a notebook.

    A term applies to a notebook when its scope is the notebook, any folder
    above it, or `ROOT_SCOPE_ID`. Harvested terms come from the keywords a
    person typed on the device and follow them: a keyword removed or edited
    on the device, or a notebook deleted, takes its terms with it. Removing a
    harvested term here suppresses it rather than deleting it, so the next
    harvest does not add it back.
    """

    def __init__(self, session_manager: DatabaseSessionManager) -> None:
        self.session_manager = session_manager

    async def list_terms(
        self, user_id: int, include_suppressed: bool = False
    ) -> list[VocabularyTerm]:
        """Return the user's terms, oldest first, optionally with removed harvested ones."""
        async with self.session_manager.session() as session:
            stmt = select(VocabularyTermDO).where(VocabularyTermDO.user_id == user_id)
            if not include_suppressed:
                stmt = stmt.where(VocabularyTermDO.is_suppressed.is_(False))
            rows = (
                await session.execute(
                    stmt.order_by(VocabularyTermDO.create_time, VocabularyTermDO.id)
                )
            ).scalars()
            return await self._describe(session, user_id, list(rows))

    async def add_terms(
        self, user_id: int, terms: Iterable[str], scope_id: int = ROOT_SCOPE_ID
    ) -> list[VocabularyTerm]:
        """Add terms by hand, restoring any that were suppressed in the same scope.

        Raises:
            FileNotFound: `scope_id` is not one of the user's folders or notebooks.
            ValueError: A term is empty or longer than `MAX_TERM_LENGTH`.
        """
        wanted = [_normalize(term) for term in terms]
        if invalid := [t for t in wanted if not t or len(t) > MAX_TERM_LENGTH]:
            raise ValueError(f"Invalid vocabulary term(s): {invalid!r}")

        async with self.session_manager.session() as session:
            await self._check_scope(session, user_id, scope_id)
            existing = await self._terms_in_scope(session, user_id, scope_id)
            result: list[VocabularyTermDO] = []
            for term in wanted:
                row = existing.get(term.casefold())
                if row is None:
                    row = VocabularyTermDO(
                        user_id=user_id,
                        term=term,
                        scope_id=scope_id,
                        source=VocabularySource.MANUAL.value,
                    )
                    session.add(row)
                    existing[term.casefold()] = row
                elif row.is_suppressed:
                    row.is_suppressed = False
                    row.source = VocabularySource.MANUAL.value
                if row not in result:
                    result.append(row)
            await session.commit()
            return await self._describe(session, user_id, result)

    async def move_term(
        self, user_id: int, term_id: int, scope_id: int
    ) -> VocabularyTerm:
        """Apply a term to a different folder, notebook, or every notebook.

        A moved term becomes the user's own. Moving a harvested term leaves a
        suppressed copy where it was harvested, so the next harvest does not
        add it there again. If the target scope already has the term, the two
        are merged.

        Raises:
            VocabularyTermNotFound: The user has no active term with `term_id`.
            FileNotFound: `scope_id` is not one of the user's folders or notebooks.
        """
        async with self.session_manager.session() as session:
            row = await self._active_term(session, user_id, term_id)
            await self._check_scope(session, user_id, scope_id)
            if scope_id == row.scope_id:
                return (await self._describe(session, user_id, [row]))[0]

            tombstone = (
                VocabularyTermDO(
                    user_id=user_id,
                    term=row.term,
                    scope_id=row.scope_id,
                    source=VocabularySource.HARVEST.value,
                    origin_file_id=row.origin_file_id,
                    is_suppressed=True,
                )
                if row.source == VocabularySource.HARVEST.value
                else None
            )
            target = (await self._terms_in_scope(session, user_id, scope_id)).get(
                row.term.casefold()
            )
            if target is None:
                row.scope_id = scope_id
                row.source = VocabularySource.MANUAL.value
                target = row
            else:
                target.is_suppressed = False
                target.source = VocabularySource.MANUAL.value
                await session.delete(row)
            # The tombstone takes the moved row's old (scope, term) slot.
            await session.flush()
            if tombstone is not None:
                session.add(tombstone)
            await session.commit()
            return (await self._describe(session, user_id, [target]))[0]

    async def remove_term(self, user_id: int, term_id: int) -> None:
        """Remove a term; a harvested one is suppressed instead of deleted.

        Raises:
            VocabularyTermNotFound: The user has no active term with `term_id`.
        """
        async with self.session_manager.session() as session:
            row = await self._active_term(session, user_id, term_id)
            if row.source == VocabularySource.HARVEST.value:
                row.is_suppressed = True
            else:
                await session.delete(row)
            await session.commit()

    async def restore_term(self, user_id: int, term_id: int) -> VocabularyTerm:
        """Bring back a removed harvested term.

        Raises:
            VocabularyTermNotFound: The user has no removed term with `term_id`.
        """
        async with self.session_manager.session() as session:
            row = await session.get(VocabularyTermDO, (term_id, user_id))
            if not row or not row.is_suppressed:
                raise VocabularyTermNotFound(
                    f"Removed vocabulary term {term_id} not found"
                )
            row.is_suppressed = False
            await session.commit()
            return (await self._describe(session, user_id, [row]))[0]

    async def harvest(self, user_id: int, file_id: int, keywords: Iterable[str]) -> int:
        """Sync a notebook's device keywords into the folder tree it belongs to.

        The scope is the highest folder above the notebook that is not a
        device system folder, so notebooks in `Work/` and `Work/Weeks/` share
        their keywords; a notebook directly inside a system folder uses that
        folder. Keywords that would not help OCR, and terms already present
        (or suppressed) in that scope or for every notebook, are skipped.

        Terms first harvested from this notebook that are no longer among its
        keywords, or that belong to the scope of a folder it has left, are
        deleted. Terms the user removed, moved, or added by hand are kept.

        Returns:
            The number of terms added.
        """
        current: dict[str, str] = {}
        for keyword in keywords:
            if (term := _clean_keyword(keyword)) is not None:
                current.setdefault(term.casefold(), term)

        async with self.session_manager.session() as session:
            note = await session.get(UserFileDO, file_id)
            if not note or note.user_id != user_id:
                return 0
            scope_id = await self._harvest_scope(session, user_id, note)
            stale = [
                row
                for row in await self._harvested_from(session, user_id, file_id)
                if row.scope_id != scope_id or row.term.casefold() not in current
            ]
            for row in stale:
                await session.delete(row)
            await session.flush()
            known = {
                term.casefold()
                for term in (
                    await session.execute(
                        select(VocabularyTermDO.term).where(
                            VocabularyTermDO.user_id == user_id,
                            VocabularyTermDO.scope_id.in_({scope_id, ROOT_SCOPE_ID}),
                        )
                    )
                ).scalars()
            }
            added = 0
            for folded, term in current.items():
                if folded in known:
                    continue
                session.add(
                    VocabularyTermDO(
                        user_id=user_id,
                        term=term,
                        scope_id=scope_id,
                        source=VocabularySource.HARVEST.value,
                        origin_file_id=file_id,
                    )
                )
                added += 1
            await session.commit()
        if added:
            logger.info(f"Harvested {added} vocabulary term(s) from file {file_id}")
        if stale:
            logger.info(
                f"Dropped {len(stale)} vocabulary term(s) no longer in file {file_id}"
            )
        return added

    async def handle_note_deleted(self, event: Event) -> None:
        """Delete the terms harvested from a notebook that was purged."""
        if not isinstance(event, NoteDeletedEvent):
            return
        async with self.session_manager.session() as session:
            await session.execute(
                delete(VocabularyTermDO).where(
                    VocabularyTermDO.user_id == event.user_id,
                    VocabularyTermDO.origin_file_id == event.file_id,
                    VocabularyTermDO.source == VocabularySource.HARVEST.value,
                    VocabularyTermDO.is_suppressed.is_(False),
                )
            )
            await session.commit()

    async def terms_for_notebook(self, user_id: int, file_id: int) -> list[str]:
        """Return the terms that apply to a notebook, nearest scope first.

        Within a scope, hand-added terms come before harvested ones. The list
        is capped at `MAX_PROMPT_TERMS`.
        """
        async with self.session_manager.session() as session:
            chain = [file_id]
            current = await session.get(UserFileDO, file_id)
            while (
                current is not None
                and current.user_id == user_id
                and current.directory_id != ROOT_SCOPE_ID
                and len(chain) < _MAX_FOLDER_DEPTH
            ):
                chain.append(current.directory_id)
                current = await session.get(UserFileDO, current.directory_id)
            chain.append(ROOT_SCOPE_ID)

            rows = (
                await session.execute(
                    select(VocabularyTermDO).where(
                        VocabularyTermDO.user_id == user_id,
                        VocabularyTermDO.scope_id.in_(chain),
                        VocabularyTermDO.is_suppressed.is_(False),
                    )
                )
            ).scalars()
            ordered = sorted(
                rows,
                key=lambda row: (
                    chain.index(row.scope_id),
                    row.source != VocabularySource.MANUAL.value,
                    row.create_time,
                    row.id,
                ),
            )

        terms: list[str] = []
        seen: set[str] = set()
        for row in ordered:
            if row.term.casefold() in seen:
                continue
            seen.add(row.term.casefold())
            terms.append(row.term)
        return terms[:MAX_PROMPT_TERMS]

    @staticmethod
    async def _active_term(
        session: AsyncSession, user_id: int, term_id: int
    ) -> VocabularyTermDO:
        row = await session.get(VocabularyTermDO, (term_id, user_id))
        if not row or row.is_suppressed:
            raise VocabularyTermNotFound(f"Vocabulary term {term_id} not found")
        return row

    @staticmethod
    async def _check_scope(session: AsyncSession, user_id: int, scope_id: int) -> None:
        if scope_id == ROOT_SCOPE_ID:
            return
        scope = await session.get(UserFileDO, scope_id)
        if not scope or scope.user_id != user_id or scope.is_active != "Y":
            raise FileNotFound(f"Vocabulary scope {scope_id} not found")

    @staticmethod
    async def _harvested_from(
        session: AsyncSession, user_id: int, file_id: int
    ) -> list[VocabularyTermDO]:
        rows = (
            await session.execute(
                select(VocabularyTermDO).where(
                    VocabularyTermDO.user_id == user_id,
                    VocabularyTermDO.origin_file_id == file_id,
                    VocabularyTermDO.source == VocabularySource.HARVEST.value,
                    VocabularyTermDO.is_suppressed.is_(False),
                )
            )
        ).scalars()
        return list(rows)

    @staticmethod
    async def _terms_in_scope(
        session: AsyncSession, user_id: int, scope_id: int
    ) -> dict[str, VocabularyTermDO]:
        rows = (
            await session.execute(
                select(VocabularyTermDO).where(
                    VocabularyTermDO.user_id == user_id,
                    VocabularyTermDO.scope_id == scope_id,
                )
            )
        ).scalars()
        return {row.term.casefold(): row for row in rows}

    @staticmethod
    async def _harvest_scope(
        session: AsyncSession, user_id: int, note: UserFileDO
    ) -> int:
        vfs = VirtualFileSystem(session)
        scope_id = note.directory_id
        current = await vfs.get_node_by_id(user_id, note.directory_id)
        for _ in range(_MAX_FOLDER_DEPTH):
            if current is None or await vfs.is_system_directory(user_id, current):
                break
            scope_id = current.id
            current = await vfs.get_node_by_id(user_id, current.directory_id)
        return scope_id

    @staticmethod
    async def _describe(
        session: AsyncSession, user_id: int, rows: list[VocabularyTermDO]
    ) -> list[VocabularyTerm]:
        """Convert rows to `VocabularyTerm`, naming their scopes and origins."""
        nodes: dict[int, UserFileDO | None] = {}

        async def node(file_id: int) -> UserFileDO | None:
            if file_id not in nodes:
                found = await session.get(UserFileDO, file_id)
                nodes[file_id] = found if found and found.user_id == user_id else None
            return nodes[file_id]

        async def path(file_id: int) -> str:
            names: list[str] = []
            current = await node(file_id)
            while current is not None and len(names) < _MAX_FOLDER_DEPTH:
                if not (
                    current.directory_id == ROOT_SCOPE_ID
                    and current.file_name in CATEGORY_CONTAINERS
                ):
                    names.append(current.file_name)
                current = (
                    await node(current.directory_id)
                    if current.directory_id != ROOT_SCOPE_ID
                    else None
                )
            return "/".join(reversed(names))

        terms = []
        for row in rows:
            origin = await node(row.origin_file_id) if row.origin_file_id else None
            terms.append(
                VocabularyTerm(
                    id=row.id,
                    term=row.term,
                    scope_id=row.scope_id,
                    source=VocabularySource(row.source),
                    create_time=row.create_time,
                    is_suppressed=row.is_suppressed,
                    origin_file_id=row.origin_file_id,
                    scope_path=await path(row.scope_id)
                    if row.scope_id != ROOT_SCOPE_ID
                    else "",
                    origin_name=origin.file_name if origin else None,
                )
            )
        return terms
