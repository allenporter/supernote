"""Unit tests for `supernote.server.utils.stopwords`."""

from __future__ import annotations

from supernote.server.utils.stopwords import STOPWORDS


def test_stopwords_contains_casefolded_english_and_hiragana_function_words() -> None:
    assert {"a", "the", "under", "what", "with", "です", "する", "した"} <= STOPWORDS
    assert all(word == word.casefold() for word in STOPWORDS)


def test_stopwords_preserves_single_letter_compound_qualifiers_and_digits() -> None:
    assert STOPWORDS.isdisjoint({"c", "d", "p", "r", "s", "t", "x", "0", "1", "100"})
