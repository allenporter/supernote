"""Tests for `supernote.server.components.wiki.models`."""

from __future__ import annotations

import pytest

from supernote.server.components.wiki.models import (
    extract_wikilinks,
    normalize_alias,
    normalize_slug,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Projects/Q3-Plan", "projects/q3-plan"),
        (" /entities/alice/ ", "entities/alice"),
        ("index", "index"),
    ],
)
def test_normalize_slug_valid(raw: str, expected: str) -> None:
    assert normalize_slug(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "../secret", "a//b", "projects/bad slug", "x" * 192],
)
def test_normalize_slug_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_slug(raw)


def test_normalize_alias() -> None:
    assert normalize_alias("  Alice   Smith ") == "alice smith"
    with pytest.raises(ValueError):
        normalize_alias("   ")


def test_extract_wikilinks_deduplicates_and_ignores_invalid() -> None:
    body = (
        "See [[entities/Alice|Alice]] and [[projects/q3-plan]] "
        "and [[entities/alice]] and [[../bad]]."
    )
    assert extract_wikilinks(body) == [
        ("entities/alice", "Alice"),
        ("projects/q3-plan", None),
    ]
