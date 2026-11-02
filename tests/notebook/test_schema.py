import base64
import io
import json
import re
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

import pytest

from supernote.notebook import (
    Link,
    Notebook,
    SupernoteMetadata,
    exceptions,
    parse_metadata,
    reconstruct,
)
from supernote.notebook.schema import (
    EquipmentType,
    FileType,
    FooterMetadata,
    HeaderMetadata,
    KeywordMetadata,
    LayerMetadata,
    LayerName,
    LayerProtocol,
    LayerType,
    LayerVisibility,
    LinkDirection,
    LinkMetadata,
    LinkType,
    PageMetadata,
    PageOrientation,
    RecognitionStatus,
    Rect,
    TitleMetadata,
    encode_layer_info,
    encode_parameters,
    extract_parameters,
    parse_layer_info,
)

from .conftest import TEST_DATA_DIR

NOTE_PATHS = sorted(TEST_DATA_DIR.glob("**/*.note"))


# --- Corpus Completeness & Round-Trip Gate ---


@pytest.mark.parametrize("note_path", NOTE_PATHS, ids=lambda p: p.name)
def test_corpus_metadata_has_no_unmodeled_extra_keys(note_path: Path) -> None:
    with note_path.open("rb") as fd:
        metadata = parse_metadata(fd)

    assert metadata.header.extra == {}, f"unmodeled header keys in {note_path.name}"
    assert metadata.footer.extra == {}, f"unmodeled footer keys in {note_path.name}"

    for page_idx, page in enumerate(metadata.pages):
        assert page.extra == {}, (
            f"unmodeled page[{page_idx}] keys in {note_path.name}: {page.extra}"
        )
        for layer_idx, layer in enumerate(page.layers or []):
            assert layer.extra == {}, (
                f"unmodeled page[{page_idx}].layers[{layer_idx}] keys in {note_path.name}"
            )

    for kw in metadata.footer.keywords:
        assert kw.extra == {}, f"unmodeled keyword keys in {note_path.name}"
    for title in metadata.footer.titles:
        assert title.extra == {}, f"unmodeled title keys in {note_path.name}"
    for link in metadata.footer.links:
        assert link.extra == {}, f"unmodeled link keys in {note_path.name}"


@pytest.mark.parametrize("note_path", NOTE_PATHS, ids=lambda p: p.name)
def test_corpus_enum_fields_resolve_to_known_members(note_path: Path) -> None:
    with note_path.open("rb") as fd:
        metadata = parse_metadata(fd)

    assert isinstance(metadata.header.file_type, FileType)
    if metadata.header.apply_equipment is not None:
        assert isinstance(metadata.header.apply_equipment, EquipmentType)

    for page in metadata.pages:
        assert isinstance(page.orientation, PageOrientation)
        assert isinstance(page.recogn_status, RecognitionStatus)
        if page.protocol is not None:
            assert isinstance(page.protocol, LayerProtocol)
        for layer in page.layers or []:
            if layer.name is not None:
                assert isinstance(layer.name, LayerName)
            if layer.protocol is not None:
                assert isinstance(layer.protocol, LayerProtocol)
            if layer.layer_type is not None:
                assert isinstance(layer.layer_type, LayerType)

    for title in metadata.footer.titles:
        if title.protocol is not None:
            assert isinstance(title.protocol, LayerProtocol)
    for link in metadata.footer.links:
        assert isinstance(link.link_type, LinkType)
        assert isinstance(link.direction, LinkDirection)


def _assert_plain_wire_values(obj: Any) -> None:
    """Ensure to_wire_dict() emits plain str/list/dict values, never Enum subclasses."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert type(k) is str
            _assert_plain_wire_values(v)
    elif isinstance(obj, list):
        for item in obj:
            _assert_plain_wire_values(item)
    else:
        assert not isinstance(obj, Enum)
        assert type(obj) is str


@pytest.mark.parametrize("note_path", NOTE_PATHS, ids=lambda p: p.name)
def test_corpus_wire_dict_roundtrip_is_lossless(note_path: Path) -> None:
    with note_path.open("rb") as fd:
        metadata = parse_metadata(fd)

    wire = metadata.to_wire_dict()
    _assert_plain_wire_values(wire)

    rebuilt = SupernoteMetadata(
        type=wire["__type__"],
        signature=wire["__signature__"],
        header=wire["__header__"],
        footer=wire["__footer__"],
        pages=wire["__pages__"],
    )
    assert rebuilt.to_wire_dict() == wire


# --- Wire Parameter Codec & Value Type Tests ---


def test_extract_and_encode_parameters_roundtrip_with_duplicates() -> None:
    raw = "<FILE_FEATURE:24><KEYWORD_00010057:100><KEYWORD_00010057:200><DIRTY:0>"
    params = extract_parameters(raw)
    assert params == {
        "FILE_FEATURE": "24",
        "KEYWORD_00010057": ["100", "200"],
        "DIRTY": "0",
    }
    assert encode_parameters(params) == raw.encode("utf-8")


def test_rect_from_wire_and_bbox_conversion() -> None:
    rect = Rect.from_wire("121,100,341,93")
    assert rect == Rect(left=121, top=100, width=341, height=93)
    assert rect.to_wire() == "121,100,341,93"
    assert rect.bbox == (121, 100, 462, 193)


@pytest.mark.parametrize(
    "bad_wire",
    [
        "",
        "10,20,30",
        "10,20,30,40,50",
        "10,20,wide,40",
        123,
    ],
)
def test_rect_rejects_invalid_wire_format(bad_wire: Any) -> None:
    with pytest.raises(exceptions.ParserException):
        Rect.from_wire(bad_wire)


def test_parse_layer_info_handles_hash_escaped_wire_json() -> None:
    wire_json = (
        '[{"layerId"#0,"name"#"Main layer","isBackgroundLayer"#false,'
        '"isAllowAdd"#false,"isCurrentLayer"#true,"isVisible"#true,'
        '"isDeleted"#false,"isAllowUp"#false,"isAllowDown"#false},'
        '{"layerId"#-1,"name"#"Background","isBackgroundLayer"#true,'
        '"isAllowAdd"#false,"isCurrentLayer"#false,"isVisible"#false,'
        '"isDeleted"#false,"isAllowUp"#false,"isAllowDown"#false}]'
    )
    entries = parse_layer_info(wire_json)
    assert entries is not None
    assert len(entries) == 2
    assert entries[0].layer_key == "MAINLAYER"
    assert entries[0].is_visible is True
    assert entries[1].layer_key == "BGLAYER"
    assert entries[1].is_visible is False


def test_parse_layer_info_handles_base64_json() -> None:
    payload = [
        {
            "layerId": 1,
            "name": "Layer #1",
            "isBackgroundLayer": False,
            "isVisible": True,
        }
    ]
    b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    entries = parse_layer_info(b64)
    assert entries is not None
    assert entries == [
        LayerVisibility(
            layer_id=1,
            is_background_layer=False,
            is_visible=True,
            name="Layer #1",
        )
    ]
    assert entries[0].layer_key == "LAYER1"


def test_parse_layer_info_preserves_hashes_in_plain_json_names() -> None:
    raw = json.dumps(
        [
            {
                "layerId": 0,
                "name": "Draft #2",
                "isBackgroundLayer": False,
                "isVisible": True,
            }
        ]
    )
    entries = parse_layer_info(raw)
    assert entries is not None
    assert entries[0].name == "Draft #2"


def test_parse_layer_info_handles_none_sentinel() -> None:
    assert parse_layer_info(None) is None
    assert parse_layer_info("none") is None


@pytest.mark.parametrize(
    "bad_payload",
    [
        "{}",
        "[123]",
        '[{"layerId": true, "isVisible": true}]',
        '[{"layerId": "zero", "isVisible": true}]',
    ],
)
def test_parse_layer_info_rejects_malformed_structures(bad_payload: str) -> None:
    with pytest.raises(exceptions.ParserException):
        parse_layer_info(bad_payload)


def test_encode_layer_info_roundtrips_with_wire_escape() -> None:
    entries = [
        LayerVisibility(
            layer_id=0,
            is_background_layer=False,
            is_visible=True,
            name="Main layer",
            is_current_layer=True,
        )
    ]
    wire_str = encode_layer_info(entries, wire_escape=True)
    assert "#" in wire_str
    assert ":" not in wire_str
    assert parse_layer_info(wire_str) == entries


# --- Block Dataclass Forward-Compatibility & Sentinel Tests ---


def test_header_metadata_preserves_unknown_equipment_and_extra_tags() -> None:
    raw = {
        "FILE_TYPE": "NOTE",
        "APPLY_EQUIPMENT": "FUTURE_N99",
        "ORIGINAL_STYLEMD5": "0",
        "FUTURE_TAG": "abc",
    }
    header = HeaderMetadata.from_params(raw)
    assert header.file_type == FileType.NOTE
    assert header.apply_equipment == "FUTURE_N99"
    assert not isinstance(header.apply_equipment, EquipmentType)
    assert header.original_style_md5 is None
    assert header.extra == {"FUTURE_TAG": "abc"}
    assert header.to_params() == raw


def test_footer_metadata_parses_positional_covers_pages_keywords_titles_links() -> None:
    raw = {
        "FILE_FEATURE": "24",
        "PAGE1": "100",
        "PAGE2": "200",
        "COVER_0": "0",
        "COVER_2": "555",
        "STYLE_style_white": "900",
        "KEYWORD_00010057": ["300", "350"],
        "TITLE_00020100": "400",
        "LINKO_00010010002000300040": "500",
        "DIRTY": "1",
    }
    footer = FooterMetadata.from_params(raw)
    assert footer.file_feature_address == 24
    assert footer.page_addresses == {"PAGE1": 100, "PAGE2": 200}
    assert footer.cover_addresses == {"COVER_0": 0, "COVER_2": 555}
    assert footer.cover_address == 555
    assert footer.style_addresses == {"STYLE_style_white": 900}
    assert footer.keyword_addresses == {"KEYWORD_00010057": [300, 350]}
    assert footer.title_addresses == {"TITLE_00020100": [400]}
    assert footer.link_addresses == {"LINKO_00010010002000300040": [500]}
    assert footer.dirty == 1
    assert footer.extra == {}
    assert footer.to_params() == raw


def test_page_metadata_handles_a5_legacy_single_layer_keys() -> None:
    raw = {
        "PAGESTYLE": "style_white",
        "DATA": "512",
        "PROTOCOL": "SN_ASA_COMPRESS",
    }
    page = PageMetadata.from_params(raw)
    assert page.is_layer_supported is False
    assert page.data_address == 512
    assert page.protocol == LayerProtocol.SN_ASA_COMPRESS
    assert page.to_wire_dict() == raw


def test_layer_metadata_roundtrips_wire_dict() -> None:
    layer_raw = {
        "LAYERTYPE": "NOTE",
        "LAYERPROTOCOL": "RATTA_RLE",
        "LAYERNAME": "MAINLAYER",
        "LAYERPATH": "0",
        "LAYERBITMAP": "447",
        "LAYERVECTORGRAPH": "0",
        "LAYERRECOGN": "0",
    }
    layer = LayerMetadata.from_params(layer_raw)
    assert layer.name == LayerName.MAINLAYER
    assert layer.protocol == LayerProtocol.RATTA_RLE
    assert layer.layer_type == LayerType.NOTE
    assert layer.bitmap_address == 447
    assert layer.to_wire_dict() == layer_raw


def test_keyword_metadata_computes_zero_based_page_index_and_roundtrips() -> None:
    kw_raw = {
        "KEYWORDSEQNO": "0",
        "KEYWORDPAGE": "2",
        "KEYWORDRECT": "10,20,30,40",
        "KEYWORDRECTORI": "10,20,30,40",
        "KEYWORDSITE": "916",
        "KEYWORDLEN": "7",
        "KEYWORD": "ks-tilt",
    }
    kw = KeywordMetadata.from_params(kw_raw)
    assert kw.page_index == 1
    assert kw.to_wire_dict() == kw_raw


def test_title_metadata_preserves_page_index_and_roundtrips() -> None:
    title_raw = {
        "TITLESEQNO": "0",
        "TITLELEVEL": "1",
        "TITLERECT": "121,100,341,93",
        "TITLERECTORI": "121,57,341,180",
        "TITLEBITMAP": "589",
        "TITLEPROTOCOL": "RATTA_RLE",
        "TITLESTYLE": "1000254",
    }
    title = TitleMetadata.from_params(title_raw, page_index=0)
    assert title.page_index == 0
    assert title.bitmap_address == 589
    assert title.to_wire_dict() == title_raw


def test_link_metadata_converts_none_sentinels_and_roundtrips_wire_dict() -> None:
    raw = {
        "LINKTYPE": "4",
        "LINKINOUT": "0",
        "LINKRECT": "50,60,70,80",
        "LINKRECTORI": "50,60,70,80",
        "LINKPROTO": "RATTA_RLE",
        "LINKSTYLE": "style_link",
        "LINKTIMESTAMP": "12345",
        "LINKBITMAP": "900",
        "LINKFILE": "aHR0cHM6Ly9leGFtcGxlLmNvbQ==",
        "LINKFILEID": "none",
        "PAGEID": "none",
    }
    link = LinkMetadata.from_params(raw, page_index=2)
    assert link.link_type == LinkType.WEB
    assert link.direction == LinkDirection.OUT
    assert link.protocol == LayerProtocol.RATTA_RLE
    assert link.file_id is None
    assert link.page_id is None
    assert link.page_index == 2
    assert link.extra == {}
    assert link.to_wire_dict() == raw


def test_supernote_metadata_to_dict_omits_private_ordering_fields() -> None:
    metadata = SupernoteMetadata(
        type="note",
        signature="SN_FILE_VER_20230015",
        header={"FILE_TYPE": "NOTE", "APPLY_EQUIPMENT": "N6"},
        footer={"FILE_FEATURE": "24"},
        pages=[{"PAGEID": "P1", "__layers__": []}],
    )
    structured = metadata.to_dict()
    assert structured["type"] == "note"
    assert structured["header"]["file_type"] == FileType.NOTE
    assert structured["header"]["apply_equipment"] == EquipmentType.N6
    assert "_wire_keys" not in structured["header"]
    assert "_wire_keys" not in structured["footer"]
    assert "_wire_keys" not in structured["pages"][0]
    assert "_wire_layer_info" not in structured["pages"][0]


def test_synthetic_link_blocks_roundtrip_through_reconstruct_and_parse_metadata(
    reconstructable_notebook: Notebook,
) -> None:
    reconstructable_notebook.links = [
        Link(
            {
                "LINKTYPE": "0",
                "LINKINOUT": "0",
                "LINKRECT": "10,20,30,40",
                "LINKTIMESTAMP": "1700000000",
                "LINKFILE": "dGVzdC5ub3Rl",
                "LINKFILEID": str(reconstructable_notebook.file_id),
                "PAGEID": str(reconstructable_notebook.page(0).page_id),
            },
            content=b"PAGE_LINK_BITMAP",
            page_number=0,
        ),
        Link(
            {
                "LINKTYPE": "4",
                "LINKINOUT": "0",
                "LINKRECT": "50,60,70,80",
                "LINKTIMESTAMP": "1700000001",
                "LINKFILE": "aHR0cHM6Ly9leGFtcGxlLmNvbQ==",
                "LINKFILEID": "none",
                "PAGEID": "none",
            },
            content=b"WEB_LINK_BITMAP",
            page_number=0,
        ),
    ]

    binary = reconstruct(reconstructable_notebook)
    reparsed = parse_metadata(io.BytesIO(binary))

    assert len(reparsed.footer.links) == 2
    for link_meta in reparsed.footer.links:
        assert link_meta.extra == {}
        assert isinstance(link_meta.link_type, LinkType)
        assert isinstance(link_meta.direction, LinkDirection)
    assert [m.link_type for m in reparsed.footer.links] == [
        LinkType.PAGE,
        LinkType.WEB,
    ]
    assert reparsed.footer.links[1].file_id is None
    assert reparsed.footer.links[1].page_id is None


# --- Executable Documentation Spec Gate (docs/notebook_spec.md) ---

SPEC_PATH = Path(__file__).resolve().parents[2] / "docs" / "notebook_spec.md"
_SPEC_SNIPPET_RE = re.compile(
    r"<!--\s*schema:\s*(\w+)\s*-->\s*```text\n(.*?)\n```",
    re.DOTALL,
)
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

_SPEC_SCHEMA_PARSERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "HeaderMetadata": HeaderMetadata.from_params,
    "FooterMetadata": FooterMetadata.from_params,
    "PageMetadata": PageMetadata.from_params,
    "LayerMetadata": LayerMetadata.from_params,
    "KeywordMetadata": KeywordMetadata.from_params,
    "TitleMetadata": TitleMetadata.from_params,
    "LinkMetadata": LinkMetadata.from_params,
}


def _load_spec_snippets() -> list[tuple[str, str]]:
    text = SPEC_PATH.read_text(encoding="utf-8")
    return [(m.group(1), m.group(2).strip()) for m in _SPEC_SNIPPET_RE.finditer(text)]


SPEC_SNIPPETS = _load_spec_snippets()


def test_notebook_spec_covers_all_metadata_dataclasses() -> None:
    documented_classes = {cls_name for cls_name, _ in SPEC_SNIPPETS}
    assert documented_classes == set(_SPEC_SCHEMA_PARSERS)


@pytest.mark.parametrize(
    ("cls_name", "wire_snippet"),
    SPEC_SNIPPETS,
    ids=[f"{cls_name}_{idx}" for idx, (cls_name, _) in enumerate(SPEC_SNIPPETS)],
)
def test_notebook_spec_snippet_parses_strictly_and_roundtrips(
    cls_name: str, wire_snippet: str
) -> None:
    parser_fn = _SPEC_SCHEMA_PARSERS[cls_name]
    params = extract_parameters(wire_snippet)
    assert params, f"empty <KEY:VALUE> block for {cls_name}"

    model = parser_fn(params)
    assert model.extra == {}, (
        f"unmodeled extra keys in docs/notebook_spec.md {cls_name} snippet: {model.extra}"
    )
    assert encode_parameters(model.to_params()).decode("utf-8") == wire_snippet


def test_notebook_spec_relative_links_resolve() -> None:
    spec_text = SPEC_PATH.read_text(encoding="utf-8")
    assert "file://" not in spec_text

    targets = _MARKDOWN_LINK_RE.findall(spec_text)
    assert targets, "expected relative links in docs/notebook_spec.md"
    for target in targets:
        if target.startswith(("http://", "https://", "#")):
            continue
        rel_path = target.split("#", 1)[0]
        resolved = (SPEC_PATH.parent / rel_path).resolve()
        assert resolved.exists(), (
            f"broken relative link in docs/notebook_spec.md: {target} -> {resolved}"
        )
