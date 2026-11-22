import pytest

from supernote.server.utils.common_words import is_common


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("the", True),
        ("API", True),
        ("events", True),
        ("Boxes", False),
        ("milestones", True),
        ("  Logic ", True),
        ("Lovelace", False),
        ("ks-tilt", False),
        ("action item", False),
        ("", False),
        ("   ", False),
    ],
)
def test_is_common(term: str, expected: bool) -> None:
    assert is_common(term) is expected
