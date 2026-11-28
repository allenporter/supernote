"""Spellings a writer uses, read from the keywords they mark on a Supernote device.

`NoteMetadataModule` stores each page's keywords in
`f_note_page_metadata.keywords_json` on every sync, so the terms for a
notebook are a query over that: a keyword removed or edited on the device, or
a notebook deleted, is gone from the next prompt without any bookkeeping.

A notebook's own keywords come first, then those of the other notebooks under
the same top-level folder (most recently updated first), so `Work/` and
`Work/Weeks/` share terms but a journal does not pick up work jargon. A
notebook with no folder of its own, directly in `Note/` or at the root, uses
only its own keywords.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageMetadataDO
from supernote.server.services.vfs import VirtualFileSystem
from supernote.server.utils.stopwords import STOPWORDS

__all__ = ["MAX_PROMPT_TERMS", "notebook_terms"]

MAX_PROMPT_TERMS = 50
"""Most terms offered to one prompt; a long list costs tokens and distracts."""

MAX_TERM_LENGTH = 64
"""Longest accepted term; device keywords can be whole sentences."""

MAX_KEYWORD_WORDS = 4
"""Longest keyword in words; longer ones are notes, not spellings."""

_MAX_FOLDER_DEPTH = 64

# Stripped from both ends of a keyword. Periods are kept so that initialisms
# such as `U.N.` survive.
_EDGE_PUNCTUATION = "-_!?,;:#*\"'`()[]{}<>/\\|~–— "

# A word the model already predicts gains nothing from being listed: measured
# over handwritten pages, padding the prompt with such words scored worse than
# listing nothing at all.
# High-frequency written English beyond `STOPWORDS`.
_ENGLISH = """
above across after again against almost alone along already although always
among another anyone anything around ask asked away back bad became because
become before began begin behind below best better between big call called came
cannot case cases certain change check clear come comes coming common country
course current day days different done draw early easy either else end enough
even ever every everything example except far find first five follow following
form found four free front full gave general get give given go goes going good
got great group half hand happen head hear held help high hold home however
idea important include included including inside instead keep kept kind know
known land large last late later least leave left less let level life like line
list little live long look looked lot low made main make makes making many
maybe mean means meant mind move much name near need needed never new next
night none note nothing number often old one open order others part parts past
people per perhaps place plan point points possible present probably problem
process public put quite rather reach read ready real really reason report
result results right run said saw say says second see seem seen self sense set
several shall short show side simple since small someone something soon sort
sound space start state still stop sure system take taken tell thing things
think though thought three time times today together took top toward try turn
two upon us use used useful using usually value view want way week well went
whether whole within without word words work working world write written year
years yes yet
"""

# Generic technical and note-taking words, common as device keywords.
_TECHNICAL = """
account action active adapter add admin api app arg argument array async auth
backend backup base bug build cache call class cli client cloud code column
command commit config configuration connect console context core count data
database debug default delete dependency deploy design dev device diff dir
directory doc docs document draft edit endpoint entry env error event export
feature fetch field file filter fix flag folder format frontend function
handler hash header host id idea image import index info init input install
instance interface issue item job json key label layer library link load local
lock log logic login loop main map merge meta method migration mock model
module name network node note null object option output package page param
parameter parse patch path payload plan platform plugin port process product
project prompt property protocol proxy query queue quick read record ref
refactor release render repo repository request reset response result review
route rule run runtime save schema score script search server service session
setting setup shell size socket source spec split stack state static status
step storage store stream string struct style sync table tag target task team
template test text theme thread throw ticket time timeout todo token tool
trace track trigger type update upload url user util validate value variable
version view watch web work workflow wrapper write
"""

# Abstract nouns used to tag pages about thinking rather than about a thing.
_ABSTRACT = """
actual agenda answer approach background benefit context decision deadline
detail details effort estimate final finding follow goal impact initial
meeting milestone original outcome outline overall overview previous priority
progress purpose question recent reference related risk scope session similar
specific summary takeaway timeline topic various
"""

_CONTENT_WORDS = frozenset(
    word for block in (_ENGLISH, _TECHNICAL, _ABSTRACT) for word in block.split()
)
_COMMON_WORDS = STOPWORDS | _CONTENT_WORDS


def _is_common(term: str) -> bool:
    """Whether `term` is a single ordinary word, allowing simple plurals.

    A phrase is never common: `action item` is worth keeping even though both
    of its words are ordinary. Plural stripping applies only to content words
    of at least 3 letters so short names/acronyms like `Wes`, `UPS`, or `AES`
    are not dropped via closed-class stopwords (`we`, `up`, `a`).
    """
    word = term.lower()
    if " " in word:
        return False
    if word in _COMMON_WORDS:
        return True
    return any(
        word.endswith(suffix)
        and len(word) - len(suffix) >= 3
        and word[: -len(suffix)] in _CONTENT_WORDS
        for suffix in ("s", "es")
    )


def _clean_keyword(keyword: str) -> str | None:
    """Return a device keyword as a term, or None if it would not help OCR."""
    term = " ".join(keyword.split()).strip(_EDGE_PUNCTUATION)
    if (
        not any(c.isalpha() for c in term)
        or len(term) > MAX_TERM_LENGTH
        or len(term.split()) > MAX_KEYWORD_WORDS
        or _is_common(term)
    ):
        return None
    return term


async def notebook_terms(
    session: AsyncSession, user_id: int, file_id: int
) -> list[str]:
    """The notebook's own terms, then its folder's, capped at `MAX_PROMPT_TERMS`."""
    vfs = VirtualFileSystem(session)
    note = await vfs.get_node_by_id(user_id, file_id)
    if note is None:
        return []
    scope_id = await _scope(vfs, user_id, note)
    file_ids = {file_id}
    if scope_id is not None:
        file_ids.update(
            node.id
            for node, _ in await vfs.list_recursive(user_id, scope_id)
            if node.is_folder != "Y"
        )
    rows = await session.scalars(
        select(NotePageMetadataDO)
        .options(
            load_only(
                NotePageMetadataDO.file_id,
                NotePageMetadataDO.keywords_json,
            )
        )
        .join(
            UserFileDO,
            (UserFileDO.id == NotePageMetadataDO.file_id)
            & (UserFileDO.user_id == NotePageMetadataDO.user_id),
        )
        .where(NotePageMetadataDO.user_id == user_id)
        .where(NotePageMetadataDO.file_id.in_(file_ids))
        .where(UserFileDO.is_active == "Y")
        .where(NotePageMetadataDO.keywords_json != "[]")
        .order_by(
            UserFileDO.update_time.desc(),
            NotePageMetadataDO.file_id,
            NotePageMetadataDO.page_index,
        )
    )
    own: list[str] = []
    rest: list[str] = []
    for page in rows:
        for keyword in page.keyword_texts:
            if term := _clean_keyword(keyword):
                (own if page.file_id == file_id else rest).append(term)
    return _dedupe(own + rest)[:MAX_PROMPT_TERMS]


def _dedupe(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        key = term.casefold()
        if key not in seen:
            seen.add(key)
            out.append(term)
    return out


async def _scope(vfs: VirtualFileSystem, user_id: int, note: UserFileDO) -> int | None:
    """The highest non-system folder above a notebook, or None if it has none."""
    if note.directory_id == 0:
        return None
    scope_id: int | None = None
    current = await vfs.get_node_by_id(user_id, note.directory_id)
    for _ in range(_MAX_FOLDER_DEPTH):
        if current is None or await vfs.is_system_directory(user_id, current):
            break
        scope_id = current.id
        if current.directory_id == 0:
            break
        current = await vfs.get_node_by_id(user_id, current.directory_id)
    return scope_id
