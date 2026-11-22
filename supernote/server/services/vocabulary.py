"""Spellings a writer uses, read from the keywords they mark on a Supernote device.

Page hashing already stores each page's keywords in
`f_note_page_metadata.keywords_json` on every sync, so the terms for a
notebook are a query over that: a keyword removed or edited on the device, or
a notebook deleted, is gone from the next prompt without any bookkeeping.

A notebook's own keywords come first, then those of the other notebooks under
the same top-level folder, so `Work/` and `Work/Weeks/` share terms but a
journal does not pick up work jargon.
"""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageMetadataDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.vfs import VirtualFileSystem
from supernote.server.utils.common_words import is_common

__all__ = [
    "MAX_KEYWORD_WORDS",
    "MAX_PROMPT_TERMS",
    "MAX_TERM_LENGTH",
    "VocabularyService",
]

MAX_PROMPT_TERMS = 200
"""Most terms offered to one prompt; a long list dilutes the instruction."""

MAX_TERM_LENGTH = 64
"""Longest accepted term; device keywords can be whole sentences."""

MAX_KEYWORD_WORDS = 4
"""Longest keyword in words; longer ones are notes, not spellings."""

_MAX_FOLDER_DEPTH = 64

# Stripped from both ends of a keyword. Periods are kept so that initialisms
# such as `U.N.` survive.
_EDGE_PUNCTUATION = "-_!?,;:#*\"'`()[]{}<>/\\|~–— "


def _clean_keyword(keyword: str) -> str | None:
    """Return a device keyword as a term, or None if it would not help OCR."""
    term = " ".join(keyword.split()).strip(_EDGE_PUNCTUATION)
    if (
        not any(c.isalpha() for c in term)
        or len(term) > MAX_TERM_LENGTH
        or len(term.split()) > MAX_KEYWORD_WORDS
        or is_common(term)
    ):
        return None
    return term


def _keywords(keywords_json: str) -> list[str]:
    try:
        entries = json.loads(keywords_json or "[]")
    except ValueError:
        return []
    if not isinstance(entries, list):
        return []
    return [
        keyword
        for entry in entries
        if isinstance(entry, dict) and isinstance(keyword := entry.get("KEYWORD"), str)
    ]


class VocabularyService:
    """Resolves the terms that apply to a notebook from its device keywords."""

    def __init__(self, session_manager: DatabaseSessionManager) -> None:
        self.session_manager = session_manager

    async def terms_for_notebook(self, user_id: int, file_id: int) -> list[str]:
        """The notebook's own terms, then its folder's, capped at `MAX_PROMPT_TERMS`."""
        async with self.session_manager.session() as session:
            note = await session.get(UserFileDO, file_id)
            if note is None or note.user_id != user_id:
                return []
            vfs = VirtualFileSystem(session)
            scope = await _scope(vfs, user_id, note)
            found = await _found(session, user_id)
            own = [term for note_id, term in found if note_id == file_id]
            scopes: dict[int, int] = {file_id: scope}
            rest: list[str] = []
            for note_id, term in found:
                if note_id == file_id:
                    continue
                if note_id not in scopes:
                    other = await session.get(UserFileDO, note_id)
                    scopes[note_id] = await _scope(vfs, user_id, other) if other else -1
                if scopes[note_id] == scope:
                    rest.append(term)
        return _dedupe(own + rest)[:MAX_PROMPT_TERMS]


async def _found(session: AsyncSession, user_id: int) -> list[tuple[int, str]]:
    """(notebook, term) for every usable keyword in active notebooks, in page order."""
    rows = await session.execute(
        select(NotePageMetadataDO.file_id, NotePageMetadataDO.keywords_json)
        .join(UserFileDO, UserFileDO.id == NotePageMetadataDO.file_id)
        .where(NotePageMetadataDO.user_id == user_id)
        .where(UserFileDO.is_active == "Y")
        .where(NotePageMetadataDO.keywords_json != "[]")
        .order_by(NotePageMetadataDO.file_id, NotePageMetadataDO.page_index)
    )
    return [
        (file_id, term)
        for file_id, keywords_json in rows.all()
        for keyword in _keywords(keywords_json)
        if (term := _clean_keyword(keyword))
    ]


def _dedupe(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        if term.casefold() not in seen:
            seen.add(term.casefold())
            out.append(term)
    return out


async def _scope(vfs: VirtualFileSystem, user_id: int, note: UserFileDO) -> int:
    """The highest non-system folder above a notebook."""
    scope_id = note.directory_id
    current = await vfs.get_node_by_id(user_id, note.directory_id)
    for _ in range(_MAX_FOLDER_DEPTH):
        if current is None or await vfs.is_system_directory(user_id, current):
            break
        scope_id = current.id
        current = await vfs.get_node_by_id(user_id, current.directory_id)
    return scope_id
