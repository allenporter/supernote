"""Words too common to be worth listing in a transcription vocabulary.

A vocabulary term helps when it is a word a model would otherwise misread: a
name, an acronym, project jargon. A word the model already predicts gains
nothing from being listed, and measured over handwritten pages, padding the
prompt with such words scored worse than listing nothing at all. Harvested
device keywords are filtered through `is_common`; terms a user adds by hand
are not.
"""

__all__ = ["is_common"]

# High-frequency written English.
_ENGLISH = """
a about above across after again against all almost alone along already also
although always am among an and another any anyone anything are around as ask
asked at away back bad be became because become been before began begin behind
being below best better between big both but by call called came can cannot
case cases certain change check clear come comes coming common could country
course current day days did different do does doing done down draw during each
early easy either else end enough even ever every everything example except
far few find first five follow following for form found four free from front
full further gave general get give given go goes going good got great group
had half hand happen has have having he head hear held help her here high him
himself his hold home how however i idea if important in include included
including inside instead into is it its itself just keep kept kind know known
land large last late later least leave left less let level life like line list
little live long look looked lot low made main make makes making many may
maybe me mean means meant might mind more most move much must my name near
need needed never new next night no none nor not note nothing now number of
off often old on once one only open or order other others our out over own
part parts past people per perhaps place plan point points possible present
probably problem process public put quite rather reach read ready real really
reason report result results right run said same saw say says second see seem
seen self sense set several shall she short should show side simple since
small so some someone something soon sort sound space start state still stop
such sure system take taken tell than that the their them themselves then
there these they thing things think this those though thought three through
time times to today together too took top toward try turn two under until up
upon us use used useful using usually value very view want was way we week
well went were what when where whether which while who whole why will with
within without word words work working world would write written year years
yes yet you your
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

_COMMON_WORDS = frozenset(
    word for block in (_ENGLISH, _TECHNICAL, _ABSTRACT) for word in block.split()
)


def is_common(term: str) -> bool:
    """Return whether `term` is a single ordinary word, allowing simple plurals.

    A phrase is never common: `action item` is worth keeping even though both
    of its words are ordinary.
    """
    word = term.strip().lower()
    if not word or any(c.isspace() for c in word):
        return False
    if word in _COMMON_WORDS:
        return True
    return any(
        word.endswith(suffix) and word[: -len(suffix)] in _COMMON_WORDS
        for suffix in ("s", "es")
    )
