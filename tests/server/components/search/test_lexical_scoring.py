"""Unit tests for `supernote.server.components.search.lexical_scoring`."""

from __future__ import annotations

import pytest

from supernote.server.components.search.lexical_scoring import (
    build_lexical_preview,
    extract_centered_snippet,
    parse_lexical_query,
    score_page_lexical,
    sql_prefilter_terms,
)


@pytest.mark.parametrize("raw_query", ["", "   ", "###", "---", "の"])
def test_parse_lexical_query_rejects_empty_and_particle_only_inputs(
    raw_query: str,
) -> None:
    assert parse_lexical_query(raw_query) is None


@pytest.mark.parametrize(
    ("raw_query", "keywords", "expected_score", "expected_preview"),
    [
        (
            "#KS-Tilt",
            ("###", "unrelated", " #ks-tilt ", "KS-TILT"),
            1.0,
            "Keywords: #ks-tilt, #unrelated",
        ),
        ('"#ks-tilt"', ("ks-tilt",), 1.0, "Keywords: #ks-tilt"),
        ("r", ("r",), 1.0, "Keywords: #r"),
        ("now", ("now",), 1.0, "Keywords: #now"),
        (
            "#roadmap #Q4",
            ("backlog", "roadmap", "Q4"),
            0.95,
            "Keywords: #roadmap, #Q4, #backlog",
        ),
        ("tilt", ("ks-tilt",), 0.92, "Keywords: #ks-tilt"),
        ("C++", ("C++17",), 0.92, "Keywords: #C++17"),
        ("C#", ("C#12",), 0.92, "Keywords: #C#12"),
        ("$100", ("$100",), 1.0, "Keywords: #$100"),
        ("how to fix ks-tilt drift", ("ks-tilt",), 0.80, "Keywords: #ks-tilt"),
        ("how to fix ocr", ("ocr",), 0.80, "Keywords: #ocr"),
        ("trap", ("ks-trapezoid",), 0.85, "Keywords: #ks-trapezoid"),
        ("ks trap", ("ks-trapezoid",), 0.85, "Keywords: #ks-trapezoid"),
        ("日本語の勉強", ("日本語の勉強メモ",), 0.92, "Keywords: #日本語の勉強メモ"),
        ("Python入門", ("Python入門",), 1.0, "Keywords: #Python入門"),
        ("人々", ("人々の暮らし",), 0.92, "Keywords: #人々の暮らし"),
        ("ㅋㅋㅋ", ("ㅋㅋㅋ",), 1.0, "Keywords: #ㅋㅋㅋ"),
    ],
)
def test_score_page_lexical_native_keywords_and_preview(
    raw_query: str,
    keywords: tuple[str, ...],
    expected_score: float,
    expected_preview: str,
) -> None:
    parsed = parse_lexical_query(raw_query)
    assert parsed is not None
    assert score_page_lexical(parsed, keywords, None) == pytest.approx(expected_score)
    assert build_lexical_preview(keywords, None, parsed) == expected_preview


@pytest.mark.parametrize(
    ("raw_query", "keywords", "text_content"),
    [
        ("a", ("ks-tilt",), "This is a note about everything."),
        ("a+", ("ks-tilt",), "Grade a on page 1."),
        ("the", ("ks-tilt",), "The quick brown fox."),
        ("1", ("ks-tilt",), "Page 1 item 1."),
        ("$a", ("ks-tilt",), "Variable a equals 1."),
        ("r", ("roadmap",), "R statistical computing notes."),
        ("what is on", ("on",), "What is going on in this meeting?"),
        ("to be or not to be", ("not",), "This page might not be ready yet."),
        ("x-ray", ("ray-tracing",), "A bright ray of sunshine."),
        ("p-value", ("business-value",), "Great resale value."),
        ("b-tree", ("family-tree",), "Planted an oak tree."),
        ("t-shirt", ("dress-shirt",), "Ironed a blue shirt."),
        ("vitamin d", ("vitamin-c",), "Take vitamin B12 daily."),
        ("c programming", ("python-programming",), "Python programming guide."),
        ("cafe\u0301", (), "Grabbed lunch at a cafe."),
        ("Python入門", (), "料理入門のレシピ。"),
        ("3月15日", (), "12月31日の予定。"),
        ("100円", (), "合計50000円です。"),
        ("人々", (), "日本人のパスポート。"),
        ("#ks-tilt", (), "ks is completely unrelated to tilt here."),
        ("#日本語 勉強", (), "日本語と英語を勉強した。"),
        ("ks-tilt", ("ks",), None),
        ("machine learning", ("sewing-machine", "spanish-learning"), None),
        ("cat", ("vacation", "category"), None),
        ("cat 日本語", ("vacation 日本語",), "日本語 on my vacation"),
        ("日本語の物理", (), "毎日日本語を勉強する。"),
        ("C#", ("C++",), "Modern C++ reference."),
        ("C++", ("Vitamin C",), "Daily vitamin C log."),
        ("$100", (), "Counted 100 resistors in bin."),
        ("$10", ("$100",), "Budget is $100 total."),
    ],
)
def test_score_page_lexical_rejects_false_positives(
    raw_query: str,
    keywords: tuple[str, ...],
    text_content: str | None,
) -> None:
    parsed = parse_lexical_query(raw_query)
    assert parsed is not None
    assert score_page_lexical(parsed, keywords, text_content) == 0.0


@pytest.mark.parametrize(
    ("raw_query", "keywords", "text_content", "expected_score", "expected_preview"),
    [
        (
            "telescope alignment?",
            (),
            "Checked telescope alignment last night.",
            0.85,
            "Checked telescope alignment last night.",
        ),
        (
            "what's don't can't telescope alignment",
            (),
            "Checked telescope alignment last night.",
            0.75,
            "Checked telescope alignment last night.",
        ),
        (
            "cafe\u0301",
            (),
            "Met at café downtown.",
            0.85,
            "Met at café downtown.",
        ),
        (
            "cost",
            (),
            "Calculated cost+tax=100 total.",
            0.85,
            "Calculated cost+tax=100 total.",
        ),
        ("issue", (), "Fixed issue#42 yesterday.", 0.85, "Fixed issue#42 yesterday."),
        (
            "C++",
            (),
            "Modern C++17 templates and concepts.",
            0.85,
            "Modern C++17 templates and concepts.",
        ),
        ("C#", (), "Upgraded C#12 compiler.", 0.85, "Upgraded C#12 compiler."),
        ("Python", (), "Python入門ノート。", 0.85, "Python入門ノート。"),
        ("Python 入門", (), "Python 入門ノート。", 0.85, "Python 入門ノート。"),
        ("3月15日", (), "次回は3月15日に開催。", 0.85, "次回は3月15日に開催。"),
        (
            "日本語を勉強する",
            (),
            "今日は日本語の勉強をした。",
            0.75,
            "今日は日本語の勉強をした。",
        ),
        ("机器学习", (), "深度学习与机器学习笔记。", 0.85, "深度学习与机器学习笔记。"),
        ("straße", (), "Berliner Straße 10.", 0.85, "Berliner Straße 10."),
        (
            "alignment mirror",
            (),
            "Primary mirror needs careful laser alignment.",
            0.75,
            "Primary mirror needs careful laser alignment.",
        ),
        (
            "optics",
            ("optics-lab",),
            "Optics bench collimation.",
            0.92 + 0.05 * 0.85,
            "[#optics-lab] Optics bench collimation.",
        ),
        (
            "cat",
            ("cat",),
            "Planning summer vacation itinerary.",
            1.0,
            "[#cat] Planning summer vacation itinerary.",
        ),
        (
            "ks-tilt",
            ("ks",),
            "Adjusted ks-tilt screw on mount.",
            0.85,
            "Adjusted ks-tilt screw on mount.",
        ),
    ],
)
def test_score_page_lexical_transcript_and_combined_boost(
    raw_query: str,
    keywords: tuple[str, ...],
    text_content: str,
    expected_score: float,
    expected_preview: str,
) -> None:
    parsed = parse_lexical_query(raw_query)
    assert parsed is not None
    assert score_page_lexical(parsed, keywords, text_content) == pytest.approx(
        expected_score
    )
    assert build_lexical_preview(keywords, text_content, parsed) == expected_preview


def test_sql_prefilter_terms_caps_clause_count() -> None:
    many_words = " ".join(f"term{i:04d}" for i in range(1200))
    parsed = parse_lexical_query(f"term0001 term0001 {many_words} 日本語 $")
    assert parsed is not None
    ascii_terms, cjk_terms = sql_prefilter_terms(parsed)
    assert len(ascii_terms) + len(cjk_terms) == 8


def test_sql_prefilter_terms_separates_ascii_and_cjk_stems() -> None:
    parsed = parse_lexical_query("Python 日本語")
    assert parsed is not None
    assert sql_prefilter_terms(parsed) == (("python",), ("日本語",))


@pytest.mark.parametrize("raw_query", ["Straße", "300K", "ﬁnance", "ﾊﾝｶｸﾒﾓ"])
def test_sql_prefilter_terms_omits_non_ascii_folded_query_stems(
    raw_query: str,
) -> None:
    parsed = parse_lexical_query(raw_query)
    assert parsed is not None
    assert sql_prefilter_terms(parsed) == ((), ())


def test_extract_centered_snippet_handles_tiny_bounds_and_head_truncation() -> None:
    assert extract_centered_snippet("Optics world", ["optics"], max_len=0) == ""
    assert extract_centered_snippet("Optics world", ["optics"], max_len=3) == "Opt"
    head_long = "Optics alignment header. " + ("Routine text. " * 20)
    assert extract_centered_snippet(head_long, ["optics"]).endswith("…")


def test_extract_centered_snippet_maps_casefold_expansion_offsets_to_raw_text() -> None:
    doc = ("ß" * 200) + " Straße " + ("x " * 200)
    snip = extract_centered_snippet(doc, ["strasse"])
    assert "Straße" in snip
    assert snip.startswith("…")
    assert snip.endswith("…")
    assert len(snip) <= 200
    assert extract_centered_snippet("ß" * 210, ["zzz"]).endswith("…")


def test_build_lexical_preview_prefers_multi_char_stems_and_preserves_ellipsis() -> (
    None
):
    doc = (
        "Check Monday morning meeting notes. " * 7
        + "Upgraded C#12 compiler on build agent. "
        + ("Routine wrap-up item. " * 5)
    )
    parsed = parse_lexical_query("C# compiler")
    assert parsed is not None
    preview = build_lexical_preview(("C#",), doc, parsed)
    assert "C#12 compiler" in preview
    assert preview.startswith("…")
    assert preview.endswith("…")

    badged = build_lexical_preview(("dotnet-c#-compiler",), doc, parsed)
    assert badged.startswith("[#dotnet-c#-compiler] …")
    assert "C#12 compiler" in badged
    assert badged.endswith("…")
    assert len(badged) <= 200


def test_build_lexical_preview_returns_empty_when_page_has_no_text_or_tags() -> None:
    parsed = parse_lexical_query("optics")
    assert parsed is not None
    assert build_lexical_preview((), None, parsed) == ""
