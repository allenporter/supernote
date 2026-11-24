"""Shared closed-class stopword vocabulary for lexical search and token-blended test embeddings.

Used by `supernote.server.components.search.lexical_scoring` and
`supernote.server.components.fake_ai.embedding` without introducing cross-component
dependencies.
"""

from __future__ import annotations

__all__ = ["STOPWORDS"]

STOPWORDS: frozenset[str] = frozenset(
    """
    a about all also am an and any are as at be been being both but by can could
    did do does doing down during each few for from further had has have having
    he her here hers herself him himself his how i if in into is it its itself
    just may me might more most must my myself no nor not now of off on once only
    or other our ours ourselves out over own same she should so some such than
    that the their theirs them themselves then there these they this those through
    to too under until up very was we were what when where which while who whom
    why will with would you your yours yourself yourselves
    です ます する した して ない ある いる これ それ から まで ため よう こと もの
    """.split()
)
"""Casefolded English function words (Snowball / PostgreSQL `english.stop`) and common
>=2-character Japanese Hiragana auxiliaries, copulas, and postpositions. Excludes content
nouns, digits, and non-pronoun single-letter qualifiers (`c`, `d`, `p`, `r`, `s`, `t`, `x`)
so compounds like `vitamin d`, `t-shirt`, `c programming`, and `p-value` preserve their qualifier."""
