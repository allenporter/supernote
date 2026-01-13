from pathlib import Path

from supernote.notebook import SupernoteMetadata, parse_metadata


def test_parse_metadata(test_note_path: Path) -> None:
    with test_note_path.open("rb") as fd:
        notebook: SupernoteMetadata = parse_metadata(fd)  # type: ignore[arg-type]
    data = notebook.header
    assert data
    assert data["FILE_TYPE"] == "NOTE"
    assert data["APPLY_EQUIPMENT"] == "N6"
    assert data["FILE_ID"] == "F202512072214597017338I6OJBpDccy1"
